"""CRAIN premium five-minute two-pass generation, based on tested v2.3."""
import re
from openai import OpenAI

def agenda_for_genre(genre):
    """A lightweight genre-specific content split without an extra API call."""
    g = genre.lower()
    if any(k in g for k in ("都市伝説", "ミステリー", "歴史", "ホラー", "謎")):
        return (
            "手稿・出来事の背景、確認できる事実、謎が生じた理由を説明する。仮説の結論はまだ述べない。",
            "未解決の論点、対立する仮説と各説の根拠・限界を比較し、最後に考察と結論を述べる。前半の歴史紹介を繰り返さない。",
        )
    if any(k in g for k in ("ファッション", "美容", "コーデ")):
        return (
            "視聴者の悩みと判断基準、素材・シルエット・組み合わせの原理を具体的に説明する。",
            "異なる場面で使える実践的な組み合わせ例、失敗しやすい点、選び方を示して締める。前半の原理の再説明はしない。",
        )
    if any(k in g for k in ("vlog", "日常", "旅行")):
        return (
            "場面の導入、具体的な出来事と感覚的な描写を中心に進める。結末や教訓は先取りしない。",
            "前半から続く新たな出来事、感情の変化と着地点を具体的に描く。出来事の再紹介はしない。",
        )
    if any(k in g for k in ("商品", "pr", "広告", "ビジネス")):
        return (
            "ターゲットの課題、起きる理由、選択基準、価値の仕組みを具体化する。実践手順は後半へ残す。",
            "具体的な使用場面・手順・注意点・判断材料を示し、自然な結論へ進める。前半の課題説明は繰り返さない。",
        )
    return (
        "テーマの中心的な疑問、原理や仕組みとその理由を具体的に説明する。実践手順やメニュー例は後半で扱う。",
        "前半の原理を実際に使うための具体的な手順、選び方、場面別の例と注意点を示す。原理の定義を繰り返さず結論へ進む。",
    )

def dedicated_prompt(fields, *, part, goal, first_text="", blueprint="", first_facts="", total_target=None, first_count=None):
    """Two-call plan: plan+first narration, then plan-aware continuation."""
    shared = f"""あなたはSNS動画の脚本家です。これは【同じ1本の5分動画】です。担当範囲以外を書かないでください。
プラットフォーム：{fields['platform']}
ジャンル：{fields['genre']}
テーマ：{fields['topic']}
視聴者：{fields['target_audience']}
話し方：{fields['speaking_style']}
追加指示：{fields['extra_instructions']}
外部検索はしていません。

共通ルール：
・抽象的な一般論より、テーマ固有の仕組み・根拠・比較・具体的場面・失敗例を優先する。具体性を捏造した数字や人名で水増ししない。
・各段落は新しい発見、具体例、検証、行動のいずれかを1つ以上追加する。「重要です」「魅力的です」だけの段落は禁止。
・冒頭は視聴者の疑問・意外な事実・切実な課題から入る。自己紹介・百科事典風の定義から始めない。
・構成はジャンル名だけで固定しない。謎なら「違和感→確かな事実→仮説の比較」、実用系なら「誤解→理由→実践」、物語なら「場面→変化→発見」など、テーマに最も適した展開を選ぶ。
・無意味な言い換えの繰り返しは避ける。ただし大切な一文の強調、伏線回収、前半の問いへの回答など目的のある反復は歓迎する。
・説明は自然な丁寧語を基本とし、指示がない限り「ございます」「おります」を多用しない。「今回は〜を解説します」「いかがでしたか」を避ける。
・未確認の固有名詞・年代・数値・論文・効果を作らない。既知の情報でも確信がなければ省略するか「確認が必要」と出力欄外で示す。
・定説/資料で確かめられること、解釈・仮説、噂や都市伝説を混同しない。証拠のない説を「有力」と決めつけない。
・科学・健康などでは古い通説を断定しない。一般的な目安と必須条件を区別し、個人差がある点は短く補足する。
・外部検索はしていないので、出典を見たふり・最新の研究を確認したふりをしない。
・1本の動画なので「前回」「次回」「お楽しみに」など別エピソードを示す表現を使わない。
・この回で書くナレーションは空白を除き{goal}文字を中心に、原則その±10%以内に収める。長すぎる説明を避けるため段落ごとの分量を事前配分する。読み上げ本文を1組の<NARRATION>タグで囲む。
・タグ内に見出し、映像指示、テロップ、字幕、注釈を入れない。
・外部調査がないため最新トレンド分析は出力しない。
"""
    if part == 1:
        return shared + """
【最重要：まず全体の設計、次に前半の本文】
次の形式で出力してください。
<BLUEPRINT>
FRONT:
1. 前半の固有論点＋必ず入れる具体的な説明・事例
2. 前半の固有論点＋視聴者に与える新しい気づき
BACK:
3. 後半で深掘りする別の論点＋比較・根拠・限界
4. 後半の別の論点＋具体例・結論で回収する冒頭の問い
</BLUEPRINT>
■ 動画タイトル
■ 企画コンセプト
■ 前半台本
<NARRATION>
前半の読み上げ本文のみを書く
</NARRATION>
■ 前半の映像・テロップ指示（簡潔に）

【設計上の制約】
・BLUEPRINTはテーマ専用の具体的な情報と視聴者が知りたい問いで作る。前後で中心論点を分ける。
・前半のナレーションはFRONTの項目1,2だけに沿って書く。
・BACKの項目3,4は前半で詳説せず、問い・伏線として示すのはよい。前半の結論や締めの挨拶は書かない。
・次の話題へ自然につながる途中で終える。
"""
    if not first_text or not blueprint:
        raise ValueError("前半本文またはBLUEPRINTが抽出できません。")
    budget = ""
    if total_target is not None and first_count is not None:
        budget = f"""【文字数の実測と残り予算】
全体目標：{total_target}文字（許容範囲：{int(total_target*0.8)}〜{int(total_target*1.2)}文字）
前半実測：{first_count}文字。後半の目標：{goal}文字。
後半の文章量は必ずこの目標を中心に調節する。全文を冗長に引き延ばさず、必要な情報を優先する。
"""
    return shared + f"""
{budget}【全体構成・確定済み：この計画を書き換えない】
<BLUEPRINT>
{blueprint}
</BLUEPRINT>
【前半で執筆済み】BLUEPRINTのFRONT項目1,2。背景を最初から説明し直さず、BACKで新しい情報を加える。重要な主張は、深掘り・対比・伏線回収など明確な意味がある場合に限り短く再提示してよい。
【今回執筆する担当】BACK項目3,4のみ。具体的な新情報・検証・展開を追加する。
【前半に登場した年代・数量など（前半の記述であり、真偽の検証済み資料ではない）】
{first_facts or '該当なし'}
後半で同じ年代・数値に言及するなら前半との整合性を確認する。確信がなければ数値や年代は繰り返さず省略する。前半で誤っていた可能性もあるため、誤った断定を踏襲しない。
【前半の末尾3文：接続確認専用・再掲禁止】
{first_text}
【出力形式：BLUEPRINTは再出力しない】
■ 後半台本
<NARRATION>
直前から自然につながる後半の新しい読み上げ本文
</NARRATION>
■ 後半の映像・テロップ指示（簡潔に）
・冒頭挨拶、機械的な振り返り、次回予告を書かず、前半最後の文から自然につなぐ。
・後半の各段落で新しい具体情報、判断材料、比較または実践例を増やす。根拠を示せない固有名詞や数値は作らない。
・結論は「謎ですね」「重要です」だけで終わらせず、冒頭の問いに対する到達点と未解決点を明確にする。
・全体の結論はこの最後の区間でだけ書く。
"""

def extract_blueprint(s):
    """Strict extraction; incomplete/ambiguous plan must not silently become fact."""
    matches = re.findall(r"<BLUEPRINT>(.*?)</BLUEPRINT>", s, flags=re.I | re.S)
    if len(matches) != 1:
        return None
    value = matches[0].strip()
    if not value or not re.search(r"(?im)^\s*FRONT\s*:", value) or not re.search(r"(?im)^\s*BACK\s*:", value):
        return None
    front, back = re.split(r"(?im)^\s*BACK\s*:", value, maxsplit=1)
    if not front.strip() or not back.strip():
        return None
    return value

def extract_narration(s):
    """Extract first complete narration block and flag malformed output.

    Multiple blocks are considered invalid for quality measurement, even if
    the first block can be used as context for the second generation.
    """
    matches = re.findall(r"<NARRATION>(.*?)</NARRATION>", s, flags=re.I | re.S)
    if not matches or not matches[0].strip():
        return None, False
    return matches[0].strip(), len(matches) == 1

def final_sentences(narration, limit=3):
    """Return last Japanese narration sentences for continuity, not the full text."""
    # Preserve sentence-final marks; line breaks alone are not treated as endings.
    sentences = [m.strip() for m in re.findall(r"[^。！？!?]+[。！？!?]*", narration) if m.strip()]
    return "".join(sentences[-limit:]) if sentences else narration[-160:]

def factual_handoff(narration, limit=4):
    """Carry a few potentially relevant factual claims; not external fact-checking."""
    sentences = [x.strip() for x in re.findall(r"[^。！？!?]+[。！？!?]*", narration) if x.strip()]
    selected = [x for x in sentences if re.search(r"[0-9０-９]|年代|世紀|年頃|およそ|約\d", x)]
    return "\n".join(f"・{x[:140]}" for x in selected[:limit])

def exact_tag_count(s):
    narration, valid = extract_narration(s)
    if not valid:
        return None
    return len(re.sub(r"\s+", "", narration))


def generate_premium_five_minute(api_key, model, fields):
    if not api_key:
        raise RuntimeError("OpenAI APIキーがありません")
    ai = OpenAI(api_key=api_key, timeout=120, max_retries=0)
    def call(prompt):
        response = ai.chat.completions.create(model=model, messages=[{"role":"user","content":prompt}], temperature=0.7)
        output = response.choices[0].message.content or ""
        if not output.strip():
            raise RuntimeError("AIの空応答")
        return output
    first_raw=call(dedicated_prompt(fields, part=1, goal=780))
    first, first_ok=extract_narration(first_raw)
    blueprint=extract_blueprint(first_raw)
    if not first_ok or not first or not blueprint:
        raise RuntimeError("前半の構造化抽出に失敗")
    first_count=len(re.sub(r"\s+","",first))
    second_raw=call(dedicated_prompt(fields,part=2,goal=max(160,1500-first_count),
        first_text=final_sentences(first),blueprint=blueprint,
        first_facts=factual_handoff(first),total_target=1500,first_count=first_count))
    second,second_ok=extract_narration(second_raw)
    if not second_ok or not second:
        raise RuntimeError("後半の構造化抽出に失敗")
    return "■ 前半\n"+first+"\n\n■ 後半\n"+second
