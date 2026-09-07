import io
import json
import os
import random
import re
import secrets
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

from ai_providers import AIConfig, generate as generate_ai, stream as stream_ai
from qbank_loader import BankValidationError, load_uploaded_file
from qbank_storage import QBankStore, new_state

SUPPORTED_AI_PROVIDERS = {"none", "gemini", "openai", "anthropic", "ollama"}


def create_app(test_config=None):
    app = Flask(__name__)
    data_dir = Path(os.environ.get("RENDER_DISK_PATH", app.instance_path))
    secret_key = os.environ.get("APP_SECRET_KEY")
    if os.environ.get("RENDER") and not secret_key and not test_config:
        raise RuntimeError("Render 部署必須設定 APP_SECRET_KEY")
    app.config.from_mapping(
        SECRET_KEY=secret_key or "qbank-development-only-secret",
        DATABASE_PATH=os.environ.get("DATABASE_PATH", str(data_dir / "qbank.sqlite3")),
        APP_PASSWORD=os.environ.get("APP_PASSWORD", ""),
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024,
        MAX_ZIP_UNCOMPRESSED_BYTES=100 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
        ALLOW_PRIVATE_AI_ENDPOINTS=not bool(os.environ.get("RENDER")),
    )
    if test_config:
        app.config.update(test_config)
    store = QBankStore(app.config["DATABASE_PATH"])
    app.extensions["qbank_store"] = store

    @app.before_request
    def ensure_browser_session():
        if request.endpoint == "healthz":
            return
        if "sid" not in session:
            session["sid"] = secrets.token_urlsafe(32)
        store.ensure_session(session["sid"])

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def current_state():
        return store.get_state(session["sid"])

    def selected_questions(state=None):
        state = state or current_state()
        return store.get_questions(session["sid"], state["selected_bank_ids"])

    def question_map(state=None):
        return {q["_key"]: q for q in selected_questions(state)}

    def stored_ai_config():
        raw = store.get_ai_config(session["sid"])
        if not raw or raw.get("provider") == "none":
            return None
        return AIConfig(raw.get("provider", ""), raw.get("model", ""),
                        raw.get("api_key", ""), raw.get("base_url", ""))

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            configured = app.config["APP_PASSWORD"]
            if configured and not secrets.compare_digest(request.form.get("password", ""), configured):
                return render_template("login.html", error="密碼錯誤", password_required=True), 401
            api_key = request.form.get("api_key", "").strip()
            provider = request.form.get("ai_provider")
            # Backward-compatible with the original Gemini-only login form/tests.
            provider = provider.strip().lower() if provider is not None else ("gemini" if api_key else "none")
            model = request.form.get("ai_model", "").strip()
            if provider == "gemini" and not model:
                model = "gemini-2.5-flash"
            if provider not in SUPPORTED_AI_PROVIDERS:
                return render_template("login.html", error="不支援的 AI provider",
                                       password_required=bool(app.config["APP_PASSWORD"])), 400
            if provider != "none" and not model:
                return render_template("login.html", error="啟用 AI 時必須填寫模型名稱",
                                       password_required=bool(app.config["APP_PASSWORD"])), 400
            if provider in {"gemini", "openai", "anthropic"} and not api_key:
                return render_template("login.html", error="此 AI provider 必須填寫 API Key",
                                       password_required=bool(app.config["APP_PASSWORD"])), 400
            store.set_ai_config(session["sid"], {
                "provider": provider, "model": model, "api_key": api_key,
                "base_url": request.form.get("ai_base_url", "").strip(),
            } if provider != "none" else None)
            session["logged_in"] = True
            return redirect(url_for("select"))
        return render_template("login.html", password_required=bool(app.config["APP_PASSWORD"]))

    @app.get("/logout")
    def logout():
        store.set_ai_config(session["sid"], None)
        session.pop("logged_in", None)
        return redirect(url_for("login"))

    @app.route("/select", methods=["GET", "POST"])
    @login_required
    def select():
        banks = store.list_banks(session["sid"])
        if request.method == "POST":
            selected_ids = list(dict.fromkeys(request.form.getlist("question_sets")))
            selected = store.get_banks(session["sid"], selected_ids)
            if not selected_ids:
                return render_template("select.html", banks=banks, error="請至少選擇一個題庫"), 400
            if len(selected) != len(selected_ids):
                return render_template("select.html", banks=banks, error="選取的題庫不存在或無權存取"), 400
            keys = [q["_key"] for bank in selected for q in bank["questions"]]
            state = new_state()
            state["selected_bank_ids"] = selected_ids
            state["current_keys"] = keys
            state["remaining_keys"] = list(keys)
            store.save_state(session["sid"], state)
            return redirect(url_for("index"))
        return render_template("select.html", banks=banks)

    @app.post("/upload")
    @login_required
    def upload():
        uploads = [f for f in request.files.getlist("question_files") if f.filename]
        if not uploads:
            flash("請選擇至少一個 JSON 或 ZIP 檔案", "error")
            return redirect(url_for("select"))
        parsed = []
        try:
            for uploaded in uploads:
                parsed.extend(load_uploaded_file(uploaded, app.config["MAX_ZIP_UNCOMPRESSED_BYTES"]))
        except BankValidationError as error:
            flash(str(error), "error")
            return redirect(url_for("select"))
        created, duplicates = 0, []
        for name, questions in parsed:
            if store.create_bank_unique(session["sid"], name, questions):
                created += 1
            else:
                duplicates.append(name)
        if created:
            flash(f"已上傳 {created} 份題庫", "success")
        if duplicates:
            flash(f"同名題庫已存在，已跳過：{', '.join(duplicates)}", "warning")
        return redirect(url_for("select"))

    @app.post("/banks/<bank_id>/delete")
    @login_required
    def delete_bank(bank_id):
        if not store.delete_bank(session["sid"], bank_id):
            flash("題庫不存在或無權刪除", "error")
            return redirect(url_for("select"))
        state = current_state()
        if bank_id in state["selected_bank_ids"]:
            store.save_state(session["sid"], new_state())
        flash("已刪除題庫", "success")
        return redirect(url_for("select"))

    @app.get("/")
    @login_required
    def index():
        state = current_state()
        if not state["current_keys"]:
            return redirect(url_for("select"))
        qmap = question_map(state)
        jump_questions = [{"key": key, "label": qmap[key]["題號"]}
                          for key in state["current_keys"] if key in qmap]
        return render_template("index.html", jump_questions=jump_questions,
                               total_questions=len(jump_questions),
                               ai_enabled=bool(stored_ai_config()))

    @app.get("/get_question")
    @login_required
    def get_question():
        state = current_state()
        if not state["current_keys"]:
            return jsonify({"error": "題庫尚未載入"}), 400
        qmap = question_map(state)
        requested_key = request.args.get("question_id")
        mode = request.args.get("mode", "random")
        question = None
        if requested_key:
            if requested_key not in state["current_keys"]:
                return jsonify({"error": "找不到指定的題目"}), 404
            question = qmap.get(requested_key)
            state["question_index"] = state["current_keys"].index(requested_key) + 1
        elif request.args.get("previous") == "true":
            state["question_index"] = max(0, state["question_index"] - 2)
            key = state["current_keys"][state["question_index"]]
            question = qmap.get(key)
            state["question_index"] += 1
        elif mode == "wrong":
            available = [key for key in state["wrong_keys"] if key in qmap]
            if available:
                question = qmap[random.choice(available)]
            else:
                return jsonify({"error": "目前沒有錯題"})
        elif mode == "random":
            available = [key for key in state["remaining_keys"] if key in qmap]
            if available:
                question = qmap[random.choice(available)]
        else:
            while state["question_index"] < len(state["current_keys"]):
                key = state["current_keys"][state["question_index"]]
                state["question_index"] += 1
                if key in qmap:
                    question = qmap[key]
                    break
        store.save_state(session["sid"], state)
        if question is None:
            return jsonify({"error": "所有題目都已出完！", "finished": True})
        result = dict(question)
        result["is_marked"] = result["_key"] in state["marked_keys"]
        result["is_multiple"] = result.get("題別") in ("複", "複選題", "多選題")
        return jsonify(result)

    @app.post("/submit_answer")
    @login_required
    def submit_answer():
        payload = request.get_json(silent=True) or {}
        key = (payload.get("question") or {}).get("_key")
        state = current_state()
        question = question_map(state).get(key)
        if not question or key not in state["current_keys"]:
            return jsonify({"error": "題目不存在或不屬於目前題庫"}), 404
        answer = "".join(sorted(re.sub(r"[^A-Z]", "", str(payload.get("answer", "")).upper())))
        correct = "".join(sorted(re.sub(r"[^A-Z]", "", str(question.get("答案", "")).upper())))
        is_correct = answer == correct
        if key not in state["answered_keys"]:
            state["answered_keys"].append(key)
        if key in state["remaining_keys"]:
            state["remaining_keys"].remove(key)
        if not is_correct and key not in state["wrong_keys"]:
            state["wrong_keys"].append(key)
        if payload.get("mode") == "wrong" and state["wrong_keys"]:
            state["wrong_answer_count"] = min(
                len(state["wrong_keys"]), state["wrong_answer_count"] + 1
            )
        store.save_state(session["sid"], state)
        return jsonify({"correct": is_correct, "right_answer": correct,
                        "total_questions": len(state["current_keys"]),
                        "answered_count_total": len(state["answered_keys"]),
                        "total_wrong": len(state["wrong_keys"]),
                        "answered_wrong": state["wrong_answer_count"]})

    @app.post("/mark_question")
    @login_required
    def mark_question():
        key = ((request.get_json(silent=True) or {}).get("question") or {}).get("_key")
        state = current_state()
        if key not in state["current_keys"] or key not in question_map(state):
            return jsonify({"error": "題目不存在"}), 404
        if key in state["marked_keys"]:
            state["marked_keys"].remove(key)
            status = "unmarked"
        else:
            state["marked_keys"].append(key)
            status = "marked"
        store.save_state(session["sid"], state)
        return jsonify({"status": status})

    @app.post("/reset_questions")
    @login_required
    def reset_questions():
        state = current_state()
        state.update(remaining_keys=list(state["current_keys"]), answered_keys=[],
                     question_index=0, wrong_answer_count=0)
        store.save_state(session["sid"], state)
        return jsonify({"status": "reset"})

    def questions_for_keys(keys):
        qmap = question_map()
        return [qmap[key] for key in keys if key in qmap]

    @app.get("/review")
    @login_required
    def review():
        return render_template("review.html", wrong_questions=questions_for_keys(current_state()["wrong_keys"]))

    @app.get("/review_marked")
    @login_required
    def review_marked():
        return render_template("review_marked.html", marked_questions=questions_for_keys(current_state()["marked_keys"]))

    @app.get("/review_ai")
    @login_required
    def review_ai():
        if not stored_ai_config():
            return redirect(url_for("index"))
        state, qmap, items = current_state(), question_map(), []
        for key, explanation in state["ai_cache"].items():
            if key in qmap:
                item = dict(qmap[key])
                item["ai_explanation"] = explanation
                items.append(item)
        return render_template("review_ai.html", q_ai=items)

    @app.get("/search")
    @login_required
    def search():
        return render_template("search.html")

    @app.get("/search_questions")
    @login_required
    def search_questions():
        keyword = request.args.get("keyword", "").strip()
        questions = selected_questions()
        if not keyword:
            return jsonify(questions)
        try:
            pattern = re.compile(keyword[2:] if keyword.startswith("r/") else re.escape(keyword), re.I)
        except re.error:
            return jsonify({"error": "正規表示式格式錯誤"}), 400
        return jsonify([q for q in questions if pattern.search(" ".join([
            str(q.get("題號", "")), str(q.get("題目", "")),
            *map(str, q.get("選項", [])), str(q.get("答案", ""))]))])

    def json_download(data, filename):
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return send_file(io.BytesIO(content), mimetype="application/json",
                         as_attachment=True, download_name=filename)

    @app.get("/save_question")
    @login_required
    def save_question():
        state = current_state()
        keys = state["marked_keys"] if request.args.get("type") == "marked" else state["wrong_keys"]
        return json_download(questions_for_keys(keys), "qbank_questions.json")

    @app.get("/save_progress")
    @login_required
    def save_progress():
        state = current_state()
        return json_download({"state": state, "questions": selected_questions(state)}, "qbank_progress.json")

    def build_prompt(question, choice="", detail=False, honest=False, choice_only=False):
        base = f"題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
        if choice_only:
            return f"{base}\n請簡短說明下列選項正確或錯誤的理由：{choice}"
        style = "提供詳細的解釋與各選項分析" if detail else "生成精簡的解釋"
        prompt = f"請以繁體中文針對以下問題{style}：\n\n{base}"
        return prompt + ("\n若題庫答案不合理，請明確指出。" if honest else "")

    def ai_context():
        config = stored_ai_config()
        if not config:
            return None, None, (jsonify({"error": "未設定 API Key，AI 詳解已停用"}), 403)
        payload = request.get_json(silent=True) or {}
        key = (payload.get("question") or {}).get("_key")
        state = current_state()
        question = question_map(state).get(key)
        if not question:
            return None, None, (jsonify({"error": "題目不存在"}), 404)
        prompt = build_prompt(question, payload.get("choice", ""),
                              request.args.get("detail") == "true",
                              request.args.get("honest") == "true",
                              request.args.get("choiceOnly") == "true")
        fingerprint = json.dumps({"provider": config.provider, "model": config.model,
                                  "base_url": config.base_url, "prompt": prompt},
                                 ensure_ascii=False, sort_keys=True)
        return (config, question, prompt, fingerprint), state, None

    @app.post("/get_ai_explanation")
    @login_required
    def get_ai_explanation():
        context, state, error = ai_context()
        if error:
            return error
        config, question, prompt, fingerprint = context
        key = question["_key"]
        if state["prompt_cache"].get(key) == fingerprint and key in state["ai_cache"]:
            return jsonify(explanation=state["ai_cache"][key], current_tokens=0,
                           total_tokens=state["total_tokens"])
        try:
            response = generate_ai(config, prompt,
                                   allow_private_endpoint=app.config["ALLOW_PRIVATE_AI_ENDPOINTS"])
            tokens = response.total_tokens
            state["ai_cache"][key], state["prompt_cache"][key] = response.text, fingerprint
            state["total_tokens"] += tokens
            store.save_state(session["sid"], state)
            return jsonify(explanation=response.text, current_tokens=tokens,
                           total_tokens=state["total_tokens"])
        except Exception:
            app.logger.exception("AI provider request failed")
            return jsonify({"error": "無法取得 AI 詳解，請確認 provider、模型、API Key 或端點"}), 502

    @app.post("/stream_ai_explanation")
    @login_required
    def stream_ai_explanation():
        context, state, error = ai_context()
        if error:
            return error
        config, question, prompt, fingerprint = context
        key, sid = question["_key"], session["sid"]

        def generate():
            if state["prompt_cache"].get(key) == fingerprint and key in state["ai_cache"]:
                yield state["ai_cache"][key]
                yield "<div data-tokens='" + json.dumps({"current_tokens": 0, "total_tokens": state["total_tokens"]}) + "' style='display:none;'></div>"
                return
            full_text, tokens = [], 0
            try:
                chunks = stream_ai(config, prompt,
                                   allow_private_endpoint=app.config["ALLOW_PRIVATE_AI_ENDPOINTS"])
                for chunk in chunks:
                    if chunk.text:
                        full_text.append(chunk.text)
                        yield chunk.text
                    tokens = chunk.total_tokens or tokens
                latest = store.get_state(sid)
                latest["ai_cache"][key], latest["prompt_cache"][key] = "".join(full_text), fingerprint
                latest["total_tokens"] += tokens
                store.save_state(sid, latest)
                yield "<div data-tokens='" + json.dumps({"current_tokens": tokens, "total_tokens": latest["total_tokens"]}) + "' style='display:none;'></div>"
            except Exception:
                app.logger.exception("AI provider streaming request failed")
                yield "\n\nAI 詳解產生失敗，請確認 provider、模型、API Key 或端點。"
        return Response(generate(), mimetype="text/plain")

    @app.errorhandler(413)
    def upload_too_large(_error):
        flash(f"上傳檔案超過 {app.config['MAX_CONTENT_LENGTH'] // 1024 // 1024} MB 限制", "error")
        return redirect(url_for("select"))

    return app


app = create_app()
