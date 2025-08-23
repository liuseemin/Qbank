import re
from flask import Flask, render_template, request, jsonify, Response
import json
import random
from pathlib import Path
# import google.generativeai as genai # 引入 Gemini SDK
from google import genai


# --- 設定 Gemini API ---
# ⚠️ 注意：將你的 API 金鑰存在環境變數中，而非直接寫在程式碼裡
import os
# 如果沒有設定環境變數，這裡會出錯，所以要先設定好
# genai.configure(api_key=os.environ.get("GEMINI_API_KEY")) 
# 選擇一個適合的模型，例如 'gemini-1.5-flash-latest'
# model = genai.GenerativeModel('gemini-2.5-flash')
# ---

# check if GEMINI_API_KEY is set in environment variable
if "GEMINI_API_KEY" not in os.environ:
    print("⚠️ GEMINI_API_KEY 環境變數未設定")
    os.environ["GEMINI_API_KEY"] = input("請輸入 Gemini API Key: ")

client = genai.Client()
MODEL = "gemini-2.5-flash"

app = Flask(__name__)

# 模擬一個儲存累積 token 數的變數
total_tokens_used = 0

# 全域資料
questions = []
wrong_questions = []
marked_questions = []
question_index = 0
remaining_questions = []

# 新增：建立一個全域字典來儲存題號對應的題目
question_index_dict = {}

answered_questions = set()

# 新增：建立一個全域快取字典來儲存 AI 詳解
ai_explanation_cache = {}

@app.route("/")
def index():
    # 傳遞所有題號給前端，以便生成下拉選單
    all_question_ids = [q.get("題號") for q in questions]
    return render_template("index.html", all_question_ids=all_question_ids, total_questions=len(questions))

@app.route("/test")
def test():
    # 傳遞所有題號給前端，以便生成下拉選單
    all_question_ids = [q.get("題號") for q in questions]
    return render_template("index_test.html", all_question_ids=all_question_ids, total_questions=len(questions))

@app.route("/review")
def review():
    return render_template("review.html", wrong_questions=wrong_questions)

@app.route("/review_marked")
def review_marked():
    return render_template("review_marked.html", marked_questions=marked_questions)

@app.route("/review_ai")
def review_ai():
    q_ai = []
    for q in questions:
        q["ai_explanation"] = ai_explanation_cache.get(q["題號"], "")
        if q["ai_explanation"] != "":
            q_ai.append(q)
    return render_template("review_ai.html", q_ai=q_ai)

@app.route("/search")
def search_page():
    return render_template("search.html")

@app.route("/get_question")
def get_question():
    global question_index, remaining_questions
    mode = request.args.get("mode", "random")
    question_id = request.args.get("question_id")

    if not questions:
        return jsonify({"error": "題庫尚未載入"})

    # 處理跳轉到特定題號的請求
    if question_id:
        try:
            if question_id in question_index_dict:
                question_index = question_index_dict[question_id]
            else:
                raise KeyError

            q = questions[question_index]
            # 修正：透過題號判斷題目是否已被標記
            q["is_marked"] = any(marked_q.get("題號") == q.get("題號") for marked_q in marked_questions)
            q["is_multiple"] = True if q.get("題別") == "複" else False
            question_index += 1
            return jsonify(q)
        except StopIteration:
            return jsonify({"error": f"找不到題號為 {question_id} 的題目"})
        except KeyError:
            return jsonify({"error": f"找不到題號為 {question_id} 的題目"})

    if mode == "wrong" and not wrong_questions:
        return jsonify({"error": "目前沒有錯題"})

    q = None
    if mode == "random":
        if remaining_questions:
            q = random.choice(remaining_questions)
            question_index = questions.index(q)
    elif mode == "order":
        if question_index < len(questions):
            q = questions[question_index]
            question_index += 1
        else:
            question_index = 0
            q = questions[question_index]
            question_index += 1
    elif mode == "wrong":
        if wrong_questions:
            q = random.choice(wrong_questions)

    if q is None:
        return jsonify({"error": "所有題目都已出完！", "finished": True})

    # 修正：確保所有回傳題目的判斷方式一致
    q["is_marked"] = any(marked_q.get("題號") == q.get("題號") for marked_q in marked_questions)
    q["is_multiple"] = True if q.get("題別") == "複" else False
    return jsonify(q)

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    global remaining_questions
    data = request.json
    q = data["question"]
    answer = data["answer"].strip().upper()

    correct = q.get("答案", "").strip().upper()
    is_correct = (answer == correct)

    if not is_correct:
        if q not in wrong_questions:
            wrong_questions.append(q)

    answered_questions.add(q.get("題號"))
    if questions[question_index_dict[q.get("題號")]] in remaining_questions:
        remaining_questions.remove(questions[question_index_dict[q.get("題號")]])
     
    return jsonify({
        "correct": is_correct,
        "right_answer": correct,
        "answered_count": "{}/{}".format(len(answered_questions), len(questions)) if questions else len(answered_questions)
    })

@app.route("/mark_question", methods=["POST"])
def mark_question():
    data = request.json
    q = data["question"]
    # 儲存題號，而不是整個題目物件
    if q.get("題號") not in [mq.get("題號") for mq in marked_questions]:
        marked_questions.append(q)
    return jsonify({"status": "marked"})

@app.route("/reset_questions", methods=["POST"])
def reset_questions():
    global remaining_questions, question_index
    remaining_questions = list(questions)
    question_index = 0
    answered_questions.clear()
    return jsonify({"status": "reset"})

@app.route("/get_ai_explanation", methods=["POST"])
def get_ai_explanation():
    global total_tokens_used
    is_detail = request.args.get("detail", "false").lower() == "true"
    data = request.json
    question = data.get("question")

    if not question:
        return jsonify({"error": "未提供題目"}), 400
    
    question_id = question["題號"]

    # 步驟 1: 檢查快取中是否有詳解
    if question_id in ai_explanation_cache:
        explanation = ai_explanation_cache[question_id]
        if explanation is not None:
            print(f"✅ 題號 {question_id} 的詳解已從快取中取得。")
            return jsonify({
                "explanation": explanation,
                "current_tokens": 0,  # 從快取中取得，不計算 token 數
                "total_tokens": total_tokens_used
            })

    # 步驟 2: 如果快取中沒有，則執行 API 呼叫
    prompt = f"請以繁體中文，針對以下問題，生成精簡的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    if is_detail:
        prompt = f"請以繁體中文，針對以下問題，生成 1 分鐘內可以閱讀完的詳解，包含關鍵概念和每個選項解釋，文字簡明，重點清楚：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
        
    try:
        # response = model.generate_content(prompt)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )
        # 移除這行程式碼，讓 AI 回傳的換行和格式得以保留
        explanation = response.text

        # 步驟 3: 將新的詳解儲存到快取中
        ai_explanation_cache[question_id] = explanation
        
        # 計算本次請求的 token 數
        prompt_tokens = response.usage_metadata.prompt_token_count
        completion_tokens = response.usage_metadata.prompt_token_count
        current_tokens = prompt_tokens + completion_tokens
        
        # 更新累積 token 數
        total_tokens_used += current_tokens

        html = review_ai()
        with open("tmp_explanation.html", "w", encoding="utf-8") as f:
            f.write(html)

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
    global total_tokens_used
    data = request.json
    question = data.get("question")

    if not question:
        return jsonify({"error": "未提供題目"}), 400
    
    question_id = question["題號"]

    # 步驟 1: 檢查快取中是否有詳解
    if question_id in ai_explanation_cache:
        print(f"✅ 題號 {question_id} 的詳解已從快取中取得。")
        explanation = ai_explanation_cache[question_id]
        return jsonify({
            "explanation": explanation,
            "current_tokens": 0,  # 從快取中取得，不計算 token 數
            "total_tokens": total_tokens_used
        })

    prompt = f"請以繁體中文，針對以下問題提供詳細的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    
    # 確保 prompt_tokens 在串流開始前計算一次
    # 因為 prompt tokens 在發送請求時就已確定
    # prompt_tokens = client.models.count_tokens(model=MODEL, contents=prompt).total_tokens

    def generate_stream():
        global total_tokens_used
        try:
            response = client.models.generate_content_stream(
                model=MODEL,
                contents=prompt
            )
            # 呼叫 genai API 並啟用串流
            for chunk in response:
                if (chunk.text):
                    yield chunk.text.encode('utf-8')
                if (chunk.usage_metadata):
                    current_tokens = chunk.usage_metadata.total_token_count
                    total_tokens_used += current_tokens
                    token_info = {
                        "current_tokens": current_tokens,
                        "total_tokens": total_tokens_used
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

def load_questions(json_paths):
    global questions, remaining_questions, question_index_dict
    all_question_files = []
    
    for path_str in json_paths:
        p = Path(path_str)
        if not p.exists():
            print(f"❌ 找不到路徑：{path_str}")
            continue

        if p.is_dir():
            # 如果是資料夾，尋找所有 .json 檔案
            print(f"📂 正在載入資料夾：{p}")
            all_question_files.extend(p.glob("*.json"))
        else:
            # 如果是單一檔案，直接加入列表
            all_question_files.append(p)

    all_questions = []
    for file_path in all_question_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    cleaned_questions = []
                    for q in data:
                        if '題目' in q:
                            q['題目'] = q['題目'].replace('\r\n', ' ').replace('\n', ' ').strip()
                        if '選項' in q and isinstance(q['選項'], list):
                            q['選項'] = [opt.replace('\r\n', ' ').replace('\n', ' ').strip() for opt in q['選項']]
                        if '題號' in q:
                            q['題號'] = f"{file_path.stem}_{q.get('題號')}"
                        cleaned_questions.append(q)
                    all_questions.extend(cleaned_questions)
                    print(f"✅ 載入檔案：{file_path}，題數：{len(cleaned_questions)}")
                else:
                    print(f"⚠️ {file_path} 格式錯誤，非陣列，略過")
        except json.JSONDecodeError:
            print(f"⚠️ {file_path} 無法解析為 JSON，略過")
        except Exception as e:
            print(f"❌ 處理檔案 {file_path} 時發生錯誤：{e}")
            
    questions = all_questions
    remaining_questions = list(questions)
    question_index_dict = {q['題號']: i for i, q in enumerate(questions)}

@app.route("/search_questions")
def search_questions():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify([])

    results = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    for q in questions:
        text = q.get("題目", "")
        opts = q.get("選項", [])
        # 題目 + 選項 全部檢查
        combined = text + " " + " ".join(opts)
        if pattern.search(combined):
            highlighted_question = pattern.sub(
                lambda m: f"<mark>{m.group(0)}</mark>", text
            )
            highlighted_options = [
                pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", o) for o in opts
            ]
            results.append({
                "題號": q.get("題號"),
                "題目": highlighted_question,
                "選項": highlighted_options,
                "答案": q.get("答案", "")
            })

    return jsonify(results)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="國考出題機（支援多題庫與模式切換）")
    parser.add_argument("json_files", nargs="+", help="一個或多個題庫 JSON 檔案或資料夾")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    load_questions(args.json_files)
    print(f"✅ 題庫已載入，總題數：{len(questions)}")
    print(f"🌐 網頁出題機：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)