from flask import Flask, render_template, request, jsonify
import json
import random
from pathlib import Path
import google.generativeai as genai # 引入 Gemini SDK

# --- 設定 Gemini API ---
# ⚠️ 注意：將你的 API 金鑰存在環境變數中，而非直接寫在程式碼裡
import os
# 如果沒有設定環境變數，這裡會出錯，所以要先設定好
genai.configure(api_key=os.environ.get("GEMINI_API_KEY")) 
# 選擇一個適合的模型，例如 'gemini-1.5-flash-latest'
model = genai.GenerativeModel('gemini-1.5-flash-latest')
# ---

app = Flask(__name__)

# 全域資料
questions = []
wrong_questions = []
marked_questions = []
question_index = 0
remaining_questions_order = []
remaining_questions_random = []

@app.route("/")
def index():
    # 傳遞所有題號給前端，以便生成下拉選單
    all_question_ids = [q.get("題號") for q in questions]
    return render_template("index.html", all_question_ids=all_question_ids)

@app.route("/review")
def review():
    return render_template("review.html", wrong_questions=wrong_questions)

@app.route("/review_marked")
def review_marked():
    return render_template("review_marked.html", marked_questions=marked_questions)

@app.route("/get_question")
def get_question():
    global question_index, remaining_questions_order, remaining_questions_random
    mode = request.args.get("mode", "random")
    question_id = request.args.get("question_id")

    if not questions:
        return jsonify({"error": "題庫尚未載入"})
    
    # 處理跳轉到特定題號的請求
    if question_id:
        q = next((q for q in questions if q.get("題號") == question_id), None)
        if q:
            q["is_marked"] = q in marked_questions
            return jsonify(q)
        else:
            return jsonify({"error": f"找不到題號為 {question_id} 的題目"})

    # 以下是處理正常出題模式的邏輯
    if mode == "order" and not remaining_questions_order:
        remaining_questions_order = list(questions)
        question_index = 0
    elif mode == "random" and not remaining_questions_random:
        remaining_questions_random = list(questions)
        random.shuffle(remaining_questions_random)
    elif mode == "wrong" and not wrong_questions:
        return jsonify({"error": "目前沒有錯題"})

    q = None
    if mode == "random":
        if remaining_questions_random:
            q = remaining_questions_random.pop(0)
    elif mode == "order":
        if remaining_questions_order:
            q = remaining_questions_order[question_index]
            question_index += 1
    elif mode == "wrong":
        if wrong_questions:
            q = random.choice(wrong_questions)

    if q is None:
        return jsonify({"error": "所有題目都已出完！", "finished": True})

    q["is_marked"] = q in marked_questions
    return jsonify(q)

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    data = request.json
    q = data["question"]
    answer = data["answer"].strip().upper()

    correct = q.get("答案", "").strip().upper()
    is_correct = (answer == correct)

    if not is_correct:
        if q not in wrong_questions:
            wrong_questions.append(q)

    return jsonify({
        "correct": is_correct,
        "right_answer": correct
    })

@app.route("/mark_question", methods=["POST"])
def mark_question():
    data = request.json
    q = data["question"]
    if q not in marked_questions:
        marked_questions.append(q)
    return jsonify({"status": "marked"})

@app.route("/reset_questions", methods=["POST"])
def reset_questions():
    global remaining_questions_order, remaining_questions_random, question_index
    remaining_questions_order = list(questions)
    remaining_questions_random = list(questions)
    random.shuffle(remaining_questions_random)
    question_index = 0
    return jsonify({"status": "reset"})

@app.route("/get_ai_explanation", methods=["POST"])
def get_ai_explanation():
    data = request.json
    question = data.get("question")

    if not question:
        return jsonify({"error": "未提供題目"}), 400

    prompt = f"請以繁體中文，針對以下問題提供詳細的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}"
    
    try:
        response = model.generate_content(prompt)
        # 移除回傳內容中的所有換行符號
        explanation = response.text.replace('\n', ' ').replace('\r', '') 
        return jsonify({"explanation": explanation})
    except Exception as e:
        print(f"Gemini API 呼叫失敗: {e}")
        return jsonify({"error": "無法取得 AI 詳解，請稍後再試。"}), 500

def load_questions(json_paths):
    global questions, remaining_questions_order, remaining_questions_random
    all_questions = []
    for path in json_paths:
        p = Path(path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    cleaned_questions = []
                    for q in data:
                        if '題目' in q:
                            q['題目'] = q['題目'].replace('\r\n', ' ').replace('\n', ' ').strip()
                        if '選項' in q and isinstance(q['選項'], list):
                            q['選項'] = [opt.replace('\r\n', ' ').replace('\n', ' ').strip() for opt in q['選項']]
                        cleaned_questions.append(q)
                    all_questions.extend(cleaned_questions)
                else:
                    print(f"⚠️ {path} 格式錯誤，非陣列，略過")
        else:
            print(f"❌ 找不到檔案：{path}")
    questions = all_questions
    remaining_questions_order = list(questions)
    remaining_questions_random = list(questions)
    random.shuffle(remaining_questions_random)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="國考出題機（支援多題庫與模式切換）")
    parser.add_argument("json_files", nargs="+", help="一個或多個題庫 JSON 檔案")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    load_questions(args.json_files)
    print(f"✅ 題庫已載入，總題數：{len(questions)}")
    print(f"🌐 網頁出題機：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)