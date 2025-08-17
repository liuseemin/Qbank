from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session
import json
import random
from pathlib import Path
from google import genai
import os

app = Flask(__name__)

APP_PASSWORD = os.environ.get("APP_PASSWORD")
app.secret_key = os.environ.get("APP_SECRET_KEY")
MODEL = "gemini-2.5-flash"

# --- 登入頁 ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        api_key = request.form.get("api_key")

        if password != APP_PASSWORD:
            return render_template("login.html", error="密碼錯誤")
        if not api_key:
            return render_template("login.html", error="請輸入 Gemini API Key")

        # 記錄 session
        session["logged_in"] = True
        session["gemini_api_key"] = api_key

        return redirect(url_for("select"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

@app.route("/select", methods=["GET", "POST"])
def select():
    available_jsons = sorted(Path(__file__).resolve().parent.joinpath('json').glob("*.json"))
    
    if request.method == "POST":
        selected_stems = request.form.getlist("question_sets")
        if not selected_stems:
            return render_template("select.html", files=available_jsons, error="請至少選擇一個題庫")

        # 將選擇的題庫 ID 儲存在 session 中
        session["selected_question_sets"] = selected_stems
        session.pop("current_question_ids", None)
        
        # 載入選定的題目 IDs，並將狀態儲存到 Session
        all_questions_for_user = []
        for stem in selected_stems:
            questions_list = ALL_QUESTIONS_DATA.get(stem, [])
            all_questions_for_user.extend(questions_list)
        
        session["current_question_ids"] = [q["題號"] for q in all_questions_for_user]
        
        # 初始化 Session 狀態
        session["wrong_questions"] = []
        session["marked_questions"] = []
        session["answered_questions"] = []
        session["remaining_question_ids"] = session["current_question_ids"].copy()
        session["question_index"] = 0
        session["total_tokens_used"] = 0

        return redirect(url_for("index"))

    return render_template("select.html", files=available_jsons)

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    # 從 session 取得當前題號列表
    current_question_ids = session.get("current_question_ids")
    
    if not current_question_ids:
        return redirect(url_for("select"))

    # 傳遞所有題號給前端，以便生成下拉選單
    # 注意：這裡使用 current_question_ids
    return render_template("index.html", all_question_ids=current_question_ids, total_questions=len(current_question_ids))

@app.route("/test")
def test():
    # 從 session 取得當前題號列表
    current_question_ids = session.get("current_question_ids")
    if not current_question_ids:
         return redirect(url_for("select")) # 如果沒有題庫，導向選擇頁

    # 傳遞所有題號給前端，以便生成下拉選單
    return render_template("index_test.html", all_question_ids=current_question_ids, total_questions=len(current_question_ids))

@app.route("/review")
def review():
    wrong_questions = session.get("wrong_questions", [])
    return render_template("review.html", wrong_questions=wrong_questions)

@app.route("/review_marked")
def review_marked():
    marked_questions = session.get("marked_questions", [])
    return render_template("review_marked.html", marked_questions=marked_questions)

@app.route("/review_ai")
def review_ai():
    q_ai = []
    # 從 session 取得 AI 詳解快取
    ai_explanation_cache = session.get("ai_explanation_cache", {})
    
    # 取得當前已選擇的題庫 ID 列表
    current_question_ids = session.get("current_question_ids", [])
    
    # 建立一個從題號到題目物件的映射，以便快速查詢
    q_id_to_question_map = {q["題號"]: q for q_list in ALL_QUESTIONS_DATA.values() for q in q_list}

    for q_id in current_question_ids:
        explanation = ai_explanation_cache.get(q_id, "")
        if explanation:
            # 從 ALL_QUESTIONS_DATA 中取得完整的題目資訊
            q = q_id_to_question_map.get(q_id)
            if q:
                q_copy = q.copy()
                q_copy["ai_explanation"] = explanation
                q_ai.append(q_copy)
                
    return render_template("review_ai.html", q_ai=q_ai)

@app.route("/get_question")
def get_question():
    mode = request.args.get("mode", "random")
    question_id = request.args.get("question_id")

    current_question_ids = session.get("current_question_ids")
    if not current_question_ids:
        return jsonify({"error": "題庫尚未載入"})

    q_id_to_question_map = {q["題號"]: q for q_list in ALL_QUESTIONS_DATA.values() for q in q_list}

    q = None
    if question_id:
        q = q_id_to_question_map.get(question_id)
        if q:
            try:
                session["question_index"] = current_question_ids.index(question_id)
            except ValueError:
                pass
        else:
            return jsonify({"error": f"找不到題號為 {question_id} 的題目"})
    elif mode == "wrong":
        wrong_questions_list = session.get("wrong_questions", [])
        if wrong_questions_list:
            q = random.choice(wrong_questions_list)
        else:
            return jsonify({"error": "目前沒有錯題"})
    elif mode == "random":
        remaining_ids = session.get("remaining_question_ids", [])
        if remaining_ids:
            q_id = random.choice(remaining_ids)
            q = q_id_to_question_map.get(q_id)
    else:  # order
        q_index = session.get("question_index", 0)
        if q_index < len(current_question_ids):
            q_id = current_question_ids[q_index]
            q = q_id_to_question_map.get(q_id)
            session["question_index"] = q_index + 1
        else:
            # 所有題目已出完
            return jsonify({"error": "所有題目都已出完！", "finished": True})

    if q is None:
        return jsonify({"error": "所有題目都已出完！", "finished": True})

    question_copy = q.copy()
    marked_ids = [mq["題號"] for mq in session.get("marked_questions", [])]
    question_copy["is_marked"] = question_copy.get("題號") in marked_ids
    question_copy["is_multiple"] = True if question_copy.get("題別") == "複" else False
    return jsonify(question_copy)

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    data = request.json
    q = data["question"]
    answer = data["answer"].strip().upper()

    correct = q.get("答案", "").strip().upper()
    is_correct = (answer == correct)

    wrong_questions_list = session.get("wrong_questions", [])
    if not is_correct:
        if q not in wrong_questions_list:
            wrong_questions_list.append(q)
            session["wrong_questions"] = wrong_questions_list
    
    answered_ids = session.get("answered_questions", [])
    answered_ids.append(q.get("題號"))
    session["answered_questions"] = answered_ids
    
    remaining_ids = session.get("remaining_question_ids", [])
    if q.get("題號") in remaining_ids:
        remaining_ids.remove(q.get("題號"))
        session["remaining_question_ids"] = remaining_ids
        
    all_q_ids = session.get("current_question_ids", [])
    
    return jsonify({
        "correct": is_correct,
        "right_answer": correct,
        "answered_count": f"{len(answered_ids)}/{len(all_q_ids)}"
    })

@app.route("/mark_question", methods=["POST"])
def mark_question():
    data = request.json
    q = data["question"]
    
    # 從 session 取得標記題目列表
    marked_questions = session.get("marked_questions", [])
    
    # 儲存題號，而不是整個題目物件
    if q.get("題號") not in [mq.get("題號") for mq in marked_questions]:
        marked_questions.append(q)
        # 將修改後的列表存回 session
        session["marked_questions"] = marked_questions
        
    return jsonify({"status": "marked"})

@app.route("/reset_questions", methods=["POST"])
def reset_questions():
    all_q_ids = session.get("current_question_ids", [])
    session["remaining_question_ids"] = all_q_ids.copy()
    session["question_index"] = 0
    session["answered_questions"] = []
    return jsonify({"status": "reset"})

@app.route("/get_ai_explanation", methods=["POST"])
def get_ai_explanation():
    total_tokens_used = session.get("total_tokens_used", 0)

    # 檢查是否已登入，並且設定api key
    if not session.get("logged_in"):
        return jsonify({"error": "未登入"}), 403

    api_key = session.get("gemini_api_key")
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 403

    client = genai.Client(api_key=api_key)

    # 取得題目
    is_detail = request.args.get("detail", "false").lower() == "true"
    data = request.json
    question = data.get("question")
    question_id = question["題號"]
    
    # 從 session 取得 AI 詳解快取
    ai_explanation_cache = session.get("ai_explanation_cache", {})
    
    # 步驟 1: 檢查 session 快取中是否有詳解
    if question_id in ai_explanation_cache:
        print(f"✅ 題號 {question_id} 的詳解已從 Session 快取中取得。")
        explanation = ai_explanation_cache[question_id]
        return jsonify({
            "explanation": explanation,
            "current_tokens": 0,
            "total_tokens": total_tokens_used
        })

    # 步驟 2: 如果快取中沒有，則執行 API 呼叫
    prompt = f"請以繁體中文，針對以下問題，生成 1 分鐘內可以閱讀完的詳解，包含關鍵概念和每個選項解釋，文字簡明，重點清楚：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    if is_detail:
        prompt = f"請以繁體中文，針對以下問題提供詳細的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
        
    try:
        # response = model.generate_content(prompt)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )
        # 移除這行程式碼，讓 AI 回傳的換行和格式得以保留
        explanation = response.text

        # 步驟 3: 將新的詳解儲存到 session 快取中
        ai_explanation_cache[question_id] = explanation
        session["ai_explanation_cache"] = ai_explanation_cache
        
        # 計算本次請求的 token 數
        current_tokens = response.usage_metadata.total_token_count
        
        # 更新累積 token 數
        total_tokens_used += current_tokens
        session["total_tokens_used"] = total_tokens_used

        return jsonify({
            "explanation": explanation,
            "current_tokens": current_tokens,
            "total_tokens": total_tokens_used
        })
    except Exception as e:
        print(f"Gemini API 呼叫失敗: {e}")
        return jsonify({"error": "無法取得 AI 詳解，請稍後再試。"}), 500
    
# 新增一個用於串流回應的路由
@app.route("/stream_ai_explanation", methods=["POST"])
def stream_ai_explanation():
    total_tokens_used = session.get("total_tokens_used", 0)

    # 檢查是否已登入，並且設定api key
    if not session.get("logged_in"):
        return jsonify({"error": "未登入"}), 403

    api_key = session.get("gemini_api_key")
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 403

    client = genai.Client(api_key=api_key)

    # 取得題目
    is_detail = request.args.get("detail", "false").lower() == "true"
    data = request.json
    question = data.get("question")
    question_id = question["題號"]

    # 從 session 取得 AI 詳解快取
    ai_explanation_cache = session.get("ai_explanation_cache", {})
    
    # 步驟 1: 檢查 session 快取中是否有詳解
    if question_id in ai_explanation_cache:
        print(f"✅ 題號 {question_id} 的詳解已從 Session 快取中取得。")
        explanation = ai_explanation_cache[question_id]
        return jsonify({
            "explanation": explanation,
            "current_tokens": 0,
            "total_tokens": total_tokens_used
        })

    # 步驟 2: 如果 session 快取中沒有，則執行 API 呼叫

    prompt = f"請以繁體中文，針對以下問題，生成 1 分鐘內可以閱讀完的詳解，包含關鍵概念和每個選項解釋，文字簡明，重點清楚：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    if is_detail:
        prompt = f"請以繁體中文，針對以下問題提供詳細的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    
    # 確保 prompt_tokens 在串流開始前計算一次
    # 因為 prompt tokens 在發送請求時就已確定
    # prompt_tokens = client.models.count_tokens(model=MODEL, contents=prompt).total_tokens

    def generate_stream():
        total_tokens_in_stream = session.get("total_tokens_used", 0)
        try:
            full_explanation = ""
            response = client.models.generate_content_stream(
                model=MODEL,
                contents=prompt
            )
            # 呼叫 genai API 並啟用串流
            for chunk in response:
                if (chunk.text):
                    yield chunk.text.encode('utf-8')
                    full_explanation += chunk.text
                if (chunk.usage_metadata):
                    current_tokens = chunk.usage_metadata.total_token_count
                    total_tokens_in_stream += current_tokens
                    session["total_tokens_used"] = total_tokens_in_stream
                    token_info = {
                        "current_tokens": current_tokens,
                        "total_tokens": total_tokens_in_stream
                    }
            
            # 將 JSON 資訊傳送給前端
            yield f"<div data-tokens='{json.dumps(token_info)}' style='display:none;'></div>".encode('utf-8')

        except Exception as e:
            # 處理可能發生的 API 錯誤
            error_message = f"無法取得 AI 詳解：{e}"
            yield f'<p style="color:red;">{error_message}</p>'.encode('utf-8')

    # 這裡回傳 Response 物件，並將生成器函式作為回應內容
    # mimetype 設為 text/html，讓瀏覽器能直接解析 HTML 標籤
    return Response(generate_stream(), mimetype='text/html')

# 修改 load_questions 為啟動時載入所有 JSON 檔
# 並將其儲存在一個全域字典中。
# 此字典的鍵為檔案名稱，值為題目列表。
ALL_QUESTIONS_DATA = {}

def load_all_question_files():
    """在應用程式啟動時載入所有題庫檔案一次。"""
    base_dir = Path(__file__).resolve().parent
    json_path = base_dir / 'json'
    available_jsons = sorted(json_path.glob("*.json"))

    for file_path in available_jsons:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # 處理並儲存每個題庫，鍵為檔案名稱
                    ALL_QUESTIONS_DATA[file_path.stem] = data
                    print(f"✅ 載入檔案：{file_path.stem}，題數：{len(data)}")
                else:
                    print(f"⚠️ {file_path} 格式錯誤，非陣列，略過")
        except json.JSONDecodeError:
            print(f"⚠️ {file_path} 無法解析為 JSON，略過")
        except Exception as e:
            print(f"❌ 處理檔案 {file_path} 時發生錯誤：{e}")

# 在應用程式啟動時呼叫此函數
load_all_question_files()

# if __name__ == "__main__":
#     import argparse
#     parser = argparse.ArgumentParser(description="國考出題機（支援多題庫與模式切換）")
#     # parser.add_argument("json_files", nargs="+", help="一個或多個題庫 JSON 檔案或資料夾")
#     parser.add_argument("--host", default="127.0.0.1")
#     parser.add_argument("--port", default=5000, type=int)
#     args = parser.parse_args()

#     default_path = ["./json"]

#     # for debug
#     for path_str in default_path:
#         p = Path(path_str)
#         if not p.exists():
#             print(f"❌ 找不到路徑：{path_str}")
#             continue

#         if p.is_dir():
#             # 如果是資料夾，尋找所有 .json 檔案
#             print(f"📂 正在載入資料夾：{p}")
#             AVAILABLE_JSONS.extend(p.glob("*.json"))
#         else:
#             # 如果是單一檔案，直接加入列表
#             AVAILABLE_JSONS.append(p)

#     # base_dir = Path(__file__).resolve().parent
#     # json_path = base_dir / 'json'
#     # AVAILABLE_JSONS.extend(json_path.glob("*.json"))

#     # load_questions(args.json_files)
#     print(f"✅ 題庫已載入，總題數：{len(questions)}")
#     print(f"🌐 網頁出題機：http://{args.host}:{args.port}")
#     app.run(host=args.host, port=args.port, debug=True)