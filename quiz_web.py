import base64
import re
from flask import Flask, render_template, request, jsonify, Response
import json
import random
from pathlib import Path
# import google.generativeai as genai # 引入 Gemini SDK
from google import genai
import io
from InquirerPy import inquirer
import locale


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

ai_key = False
if os.environ["GEMINI_API_KEY"] == "":
    print("⚠️ 無有效 Gemini API Key, 啟動無詳解模式")
    client = None
    ai_key = False
else:
    client = genai.Client()
    ai_key = True
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
wrong_questions_answer_count = 0
prev_question_index = 0

# 新增：建立一個全域字典來儲存題號對應的題目
question_index_dict = {}

answered_questions = set()

# 新增：建立一個全域快取字典來儲存 AI 詳解
ai_explanation_cache = {}
prompt_cache = {}

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
    with open("wrong_questions.json", "w", encoding="utf-8") as f:
        json.dump(wrong_questions, f, ensure_ascii=False, indent=2)
    return render_template("review.html", wrong_questions=wrong_questions)

@app.route("/save_question")
def save_question():
    type = request.args.get("type", "")
    if type == "wrong":
        questions_to_save = wrong_questions
    elif type == "marked":
        questions_to_save = marked_questions
    else:
        return "無效的類型", 400
    data = json.dumps(questions_to_save, ensure_ascii=False, indent=2)
    file_obj = io.BytesIO()
    file_obj.write(data.encode("utf-8"))
    file_obj.seek(0)
    # 讓使用者下載檔案
    # def a function to remove q['題號']'s "_number" part for all q in wrong_questions
    def remove_suffixs(q):
        return re.sub(r'_\d+$', '', q['題號'])
        
    default_filename = '+'.join({remove_suffixs(q) for q in questions_to_save}) + "_" + type + ".json"
    from urllib.parse import quote
     # 使用 RFC 5987 編碼來處理非 ASCII 字元
    return Response(file_obj, mimetype="application/json", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(default_filename)}"})

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

@app.route("/save_progress")
def save_progress():
    data = {
            "questions": questions,
            "answered_questions": list(answered_questions),
            "wrong_questions": wrong_questions,
            "marked_questions": marked_questions,
            "question_index_dict": question_index_dict,
            "wrong_questions_answer_count": wrong_questions_answer_count,
            "remaining_questions": remaining_questions,
            "question_index": question_index
        }
    file_obj = io.BytesIO()
    file_obj.write(json.dumps(data, indent=2).encode("utf-8"))
    file_obj.seek(0)
    # 讓使用者下載檔案
    return Response(file_obj, mimetype="application/json", headers={"Content-Disposition": "attachment; filename=progress.json"})

@app.route("/get_question")
def get_question():
    global question_index, remaining_questions, wrong_questions, wrong_questions_answer_count, prev_question_index
    mode = request.args.get("mode", "random")
    question_id = request.args.get("question_id")
    prev = request.args.get("prev", "false").lower() == "true"
    long = request.args.get("long", "false").lower() == "true"

    if not questions:
        return jsonify({"error": "題庫尚未載入"})

    if prev:
        question_index = max(0, question_index - 2)
        if long:
            q = questions[prev_question_index]
            question_index = prev_question_index
        else:
            q = questions[question_index]
            question_index += 1
        # 透過題號判斷題目是否已被標記
        q["is_marked"] = any(marked_q.get("題號") == q.get("題號") for marked_q in marked_questions)
        q["is_multiple"] = True if q.get("題別") == "複" else False

        
        return jsonify(q)
    
    # 處理跳轉到特定題號的請求
    if question_id:
        try:
            if question_id in question_index_dict:
                question_index = question_index_dict[question_id]
            else:
                raise KeyError

            q = questions[question_index]
            # 透過題號判斷題目是否已被標記
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
            prev_question_index = question_index
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
            # q = random.choice(wrong_questions)
            q = wrong_questions[0]
            wrong_questions_answer_count += 1
            wrong_questions.remove(q)
            wrong_questions.append(q)
            if wrong_questions_answer_count >= len(wrong_questions):
                wrong_questions_answer_count = 0
                random.shuffle(wrong_questions)

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
            # open a file to save every wrong question as history
            with open("wrong_questions_history.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(q, ensure_ascii=False, indent=2))

    answered_questions.add(q.get("題號"))
    if questions[question_index_dict[q.get("題號")]] in remaining_questions:
        remaining_questions.remove(questions[question_index_dict[q.get("題號")]])
     
    return jsonify({
        "correct": is_correct,
        "right_answer": correct,
        # "answered_count": "{}/{}".format(len(answered_questions), len(questions)) if questions else len(answered_questions),
        "total_questions": len(questions),
        "answered_count_total": len(answered_questions),
        "total_wrong": len(wrong_questions),
        "answered_wrong": wrong_questions_answer_count
    })

@app.route("/mark_question", methods=["POST"])
def mark_question():
    data = request.json
    q = data["question"]
    # 儲存題號，而不是整個題目物件
    if q.get("題號") not in [mq.get("題號") for mq in marked_questions]:
        marked_questions.append(q)
        return jsonify({"status": "marked"})
    else:
        # 如果已經標記過，則取消標記
        marked_questions[:] = [mq for mq in marked_questions if mq.get("題號") != q.get("題號")]
        return jsonify({"status": "unmarked"})

@app.route("/reset_questions", methods=["POST"])
def reset_questions():
    global remaining_questions, question_index, answered_questions
    remaining_questions = list(questions)
    question_index = 0
    answered_questions.clear()
    return jsonify({"status": "reset"})

def generate_prompt(question, choice, is_detail=False, is_honest=False, is_choiceOnly=False):
    question_part = f"題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"
    prompt = f"請以繁體中文，針對以下問題，生成精簡的解釋：\n\n{question_part}"
    if is_detail:
        prompt = f"請以繁體中文，針對以下問題，生成 1 分鐘內可以閱讀完的詳解，包含關鍵概念和每個選項解釋，文字簡明，重點清楚：\n\n{question_part}"
    
    prompt += "\n\n簡要說明答題關鍵知識，若需要分類、分級、分型等知識也請簡要列出完整分級。"
    
    if is_choiceOnly:
        prompt = f"題目：{question['題目']}\n答案：{question['答案']}\n請簡短說明下列選項正確或錯誤的理由：\n{choice}"

    if is_honest:
        prompt += "\n\n若答案不合理則要公正的指出。"

    print(f"[prompt] {prompt.replace('\n', ' ')}")
    
    return prompt


@app.route("/get_ai_explanation", methods=["POST"])
def get_ai_explanation():
    if ai_key == False:
        return jsonify({"error": "未設定 API Key，無法使用 AI 詳解"}), 400
    global total_tokens_used
    is_detail = request.args.get("detail", "false").lower() == "true"
    is_honest = request.args.get("honest", "false").lower() == "true"
    is_choiceOnly = request.args.get("choiceOnly", "false").lower() == "true"
    data = request.json
    question = data.get("question")
    choice = data.get("choice")

    if not question:
        return jsonify({"error": "未提供題目"}), 400
    
    question_id = question["題號"]

    question_part = f"題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"

    # 如果題目中有"組合題"，找出後面的第一組數字做為題號，並將該題號的題目加入prompt中
    match = re.search(r"組合題.*?(\d+)", question['題目'])
    if match:
        related_q_num = match.group(1)
        related_q_id = f"{question_id.rsplit('_', 1)[0]}_{related_q_num}"
        if related_q_id in question_index_dict:
            related_q = questions[question_index_dict[related_q_id]]
            related_part = f"相關題目：{related_q['題目']}"
            question_part = related_part + "\n\n" + question_part
    
    # 先設定prompt
    prompt = generate_prompt(question, choice, is_detail, is_honest, is_choiceOnly)

    # 檢查快取中是否有詳解，有的話直接回傳，如果prompt不一樣也繼續
    if question_id in ai_explanation_cache and prompt_cache[question_id] == prompt:
        explanation = ai_explanation_cache[question_id]
        if explanation is not None:
            print(f"✅ 題號 {question_id} 的詳解已從快取中取得。")
            return jsonify({
                "explanation": explanation,
                "current_tokens": 0,  # 從快取中取得，不計算 token 數
                "total_tokens": total_tokens_used
            })
    

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
        prompt_cache[question_id] = prompt
        
        # 計算本次請求的總 token 數 (input + output)
        current_tokens = response.usage_metadata.total_token_count
        
        # 更新累積 token 數
        total_tokens_used += current_tokens

        # html = review_ai()
        # with open("tmp_explanation.html", "w", encoding="utf-8") as f:
        #     f.write(html)

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
    if ai_key == False:
        return jsonify({"error": "未設定 API Key，無法使用 AI 詳解"}), 400
    global total_tokens_used
    is_detail = request.args.get("detail", "false").lower() == "true"
    is_honest = request.args.get("honest", "false").lower() == "true"
    is_choiceOnly = request.args.get("choiceOnly", "false").lower() == "true"
    data = request.json
    question = data.get("question")
    choice = data.get("choice")

    if not question:
        return jsonify({"error": "未提供題目"}), 400
    
    question_id = question["題號"]

    question_part = f"題目：{question['題目']}\n選項：{' '.join(question['選項'])}\n答案：{question['答案']}"

    # 如果題目中有"組合題"，找出後面的第一組數字做為題號，並將該題號的題目加入prompt中
    match = re.search(r"組合題.*?(\d+)", question['題目'])
    if match:
        related_q_num = match.group(1)
        related_q_id = f"{question_id.rsplit('_', 1)[0]}_{related_q_num}"
        if related_q_id in question_index_dict:
            related_q = questions[question_index_dict[related_q_id]]
            related_part = f"相關題目：{related_q['題目']}"
            question_part = related_part + "\n\n" + question_part
    
    # 先設定prompt
    prompt = generate_prompt(question, choice, is_detail, is_honest, is_choiceOnly)

    # 檢查快取中是否有詳解，有的話直接回傳，如果prompt不一樣也繼續
    if question_id in ai_explanation_cache and prompt_cache[question_id] == prompt:
        explanation = ai_explanation_cache[question_id]
        if explanation is not None:
            
            print(f"✅ 題號 {question_id} 的詳解已從快取中取得。")
            def response():
                token_info = {
                    "current_tokens": 0,  # 從快取中取得，不計算 token 數
                    "total_tokens": total_tokens_used
                }
                yield explanation.encode('utf-8')
                yield f"<div data-tokens='{json.dumps(token_info)}' style='display:none;'></div>".encode('utf-8')
            return Response(response(), mimetype='text/html')
    
    # 確保 prompt_tokens 在串流開始前計算一次
    # 因為 prompt tokens 在發送請求時就已確定
    # prompt_tokens = client.models.count_tokens(model=MODEL, contents=prompt).total_tokens

    def generate_stream():
        global total_tokens_used

        final_current_tokens = 0
        full_explanation = ""
        try:
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
                    final_current_tokens = chunk.usage_metadata.total_token_count
            
            if final_current_tokens > 0:
                total_tokens_used += final_current_tokens
                token_info = {
                    "current_tokens": final_current_tokens,
                    "total_tokens": total_tokens_used
                }
                ai_explanation_cache[question_id] = full_explanation
                prompt_cache[question_id] = prompt
            
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
        
        keybindings = {
            "toggle-all": [{"key": "c-a"}],
            "toggle-all-false": [{"key": "c-d"}],
        }

        if p.is_dir():
            # 如果是資料夾，尋找所有 .json 檔案
            print(f"📂 正在載入資料夾：{p}")
            all_question_files.extend(p.glob("*.json"))
            locale.setlocale(locale.LC_COLLATE, "zh_TW.UTF-8")  # 設定為系統預設語系，確保排序正確
            all_question_files = sorted(all_question_files, key=lambda x: locale.strxfrm(x.name))  # 使用 locale 進行排序
            all_question_files = inquirer.checkbox(message="請選擇要載入的題庫檔案\n",
                                choices=all_question_files if all_question_files else [],
                                keybindings=keybindings,
                                enabled_symbol="⬢", disabled_symbol="⬡", instruction='[Space 選擇] [Enter完成] [Ctrl + A 全選] [Ctrl + D 反選] [Ctrl + C 取消]').execute()
        else:
            # 如果是單一檔案，直接加入列表
            all_question_files.append(p)

    all_questions = []
    for file_path in all_question_files:
        image_folder = file_path.parent / (file_path.stem + "_images")
        if image_folder.exists():
            # 讀入圖片檔案
            image_files = list(image_folder.glob("*.png"))

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
                        qeustion_stem = re.match(r'^(.*?)(?:_\d+)$', q['題號'])
                        if '題號' in q and qeustion_stem.group(1) not in f"{file_path.stem}":
                            q['題號'] = f"{file_path.stem}_{q.get('題號')}"
                            # 如果圖片資料夾中有與題號相同的圖片，則加入題目中
                            if image_folder.exists():
                                for image_file in image_files:
                                    if image_file.stem == q['題號']:
                                        print(f"　 🖼️ 找到題號 {q['題號']} 的圖片：{(file_path.stem + '_images')}/{image_file.name}")
                                        # 存入base64編碼的圖片
                                        with open(image_file, "rb") as img_f:
                                            img_data = img_f.read()
                                            img_base64 = "data:image/png;base64," + base64.b64encode(img_data).decode('utf-8')
                                            q['圖片'] = img_base64
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

    # 自動開啟網頁
    if args.open:
        import webbrowser
        webbrowser.open(f"http://{args.host}:{args.port}")

@app.route("/search_questions")
def search_questions():
    keyword = request.args.get("keyword", "").strip()
    if keyword == "":
        return jsonify(questions)

    results = []
    # pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    if keyword.startswith('r/'):
        # 移除標記，將剩下的字串視為 regular expression
        regex_pattern = keyword[2:]
        pattern = re.compile(regex_pattern, re.IGNORECASE)
    else:
        # 否則，視為純文字，進行轉義
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    for q in questions:
        id = q.get("題號", "")
        text = q.get("題目", "")
        opts = q.get("選項", [])
        ans = q.get("答案", "")
        # 題目 + 選項 全部檢查
        combined = id + " " + text + " " + " ".join(opts) + " 答案:" + ans
        if pattern.search(combined):
            highlighted_question = pattern.sub(
                lambda m: f"<mark>{m.group(0)}</mark>", text
            )
            highlighted_options = [
                pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", o) for o in opts
            ]
            highlighted_ans = [
                pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", ans)
            ]
            results.append({
                "題號": q.get("題號"),
                "題目": highlighted_question,
                "圖片": q.get("圖片", ""),
                "選項": highlighted_options,
                "答案": highlighted_ans
            })

    return jsonify(results)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="國考出題機（支援多題庫與模式切換）")
    parser.add_argument("json_files", nargs="*", help="一個或多個題庫 JSON 檔案或資料夾")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    parser.add_argument("--wrong", "-w", type=str, help="載入錯題檔案")
    parser.add_argument("--save", "-s", type=str, help="載入進度檔案")
    parser.add_argument("--open", "-o", action="store_true", help="自動開啟網頁")
    args = parser.parse_args()

    # BUG: load ok but bug in some cases (index problem)
    if args.save:
        try:
            with open(args.save, "r", encoding="utf-8") as f:
                data = json.load(f)
                questions = data.get("questions", [])
                answered_questions = set(data.get("answered_questions", []))
                wrong_questions = data.get("wrong_questions", [])
                marked_questions = data.get("marked_questions", [])
                question_index_dict = {q['題號']: i for i, q in enumerate(questions)}
                wrong_questions_answer_count = data.get("wrong_questions_answer_count", 0)
                remaining_questions = data.get("remaining_questions", list(questions))
                question_index = data.get("question_index", 0)
                print(f"✅ 進度檔案已載入，總題數：{len(questions)}，已答題數：{len(answered_questions)}")
        except Exception as e:
            print(f"❌ 載入進度檔案失敗：{e}")
    else:
        load_questions(args.json_files)
        print(f"✅ 題庫已載入，總題數：{len(questions)}")
    
    # load_questions(args.json_files)
    # print(f"✅ 題庫已載入，總題數：{len(questions)}")

    if args.wrong:
        def load_wrong_questions(json_path):
            global wrong_questions
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        wrong_questions = data
                        print(f"✅ 載入錯題檔案：{json_path}，題數：{len(wrong_questions)}")
                    else:
                        print(f"⚠️ {json_path} 格式錯誤，非陣列，略過")
            except Exception as e:
                print(f"❌ 處理錯題檔案 {json_path} 時發生錯誤：{e}")
        load_wrong_questions(args.wrong)
        print(f"✅ 錯題檔案已載入，總題數：{len(wrong_questions)}")
    
    print(f"🌏 網頁出題機：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)

