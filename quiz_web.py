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
model = genai.GenerativeModel('gemini-2.5-flash')
# ---

app = Flask(__name__)

# 模擬一個儲存累積 token 數的變數
total_tokens_used = 0

# 全域資料
questions = []
wrong_questions = []
marked_questions = []
question_index = 0
remaining_questions_order = []
remaining_questions_random = []

# 新增：建立一個全域快取字典來儲存 AI 詳解
ai_explanation_cache = {}

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
        try:
            jump_index = next(i for i, q in enumerate(questions) if q.get("題號") == question_id)
            question_index = jump_index
            
            if mode == "order":
                remaining_questions_order = questions[question_index:]

            q = questions[question_index]
            # 修正：透過題號判斷題目是否已被標記
            q["is_marked"] = any(marked_q.get("題號") == q.get("題號") for marked_q in marked_questions)
            question_index += 1
            return jsonify(q)
        except StopIteration:
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

    # 修正：確保所有回傳題目的判斷方式一致
    q["is_marked"] = any(marked_q.get("題號") == q.get("題號") for marked_q in marked_questions)
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
    # 儲存題號，而不是整個題目物件
    if q.get("題號") not in [mq.get("題號") for mq in marked_questions]:
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

    # 步驟 2: 如果快取中沒有，則執行 API 呼叫

    prompt = f"請以繁體中文，針對以下問題提供詳細的解釋：\n\n題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    
    try:
        response = model.generate_content(prompt)
        # 移除這行程式碼，讓 AI 回傳的換行和格式得以保留
        explanation = response.text

        # 步驟 3: 將新的詳解儲存到快取中
        ai_explanation_cache[question_id] = explanation
        
        # 計算本次請求的 token 數
        prompt_tokens = model.count_tokens(prompt).total_tokens
        completion_tokens = model.count_tokens(explanation).total_tokens
        current_tokens = prompt_tokens + completion_tokens
        
        # 更新累積 token 數
        total_tokens_used += current_tokens

        return jsonify({
            "explanation": explanation,
            "current_tokens": current_tokens,
            "total_tokens": total_tokens_used
        })
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