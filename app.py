from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 青森市の市区町村コード
AREA_CODE = "0220100"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def split_search_keywords(value):
    """自由検索欄を複数キーワードに分割する"""
    if not value:
        return []
    return [keyword.casefold() for keyword in re.split(r'[\s,、。]+', str(value).strip()) if keyword]


def normalize_truthy(value):
    """真偽値の表現ゆれを安全に標準化する"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'true', '1', 'yes', 'y', 'on', '可', 'あり', '対応', '対応あり'}:
            return True
        if normalized in {'false', '0', 'no', 'n', 'off', '不可', 'なし', '未対応'}:
            return False
    return bool(value)


def has_criterion(criteria, *names):
    """検索条件のキー名ゆれを受け取り、選択されているか確認する"""
    for name in names:
        value = criteria.get(name)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            if any(str(item).strip() not in {'', 'false', 'False', 'off', 'OFF'} for item in value):
                return True
            continue
        if value not in ('', 'false', 'False', 'off', 'OFF'):
            return True
    return False


def shelter_bool_value(shelter, *names):
    """避難所データのキー名ゆれから真偽値を得る"""
    for name in names:
        if name in shelter:
            return normalize_truthy(shelter.get(name))
    return False


def shelter_disaster_set(shelter):
    """避難所の災害情報を正規化して集合にする"""
    values = set()
    for item in shelter.get('disaster_types', []) or []:
        values.add(str(item).strip())
    for disaster_name, aliases in {
        '地震': ('earthquake', 'earthquake_safe', '地震'),
        '洪水': ('flood', 'flood_safe', '洪水'),
        '土砂崩れ': ('landslide', 'landslide_safe', '土砂崩れ'),
        '津波': ('tsunami', 'tsunami_safe', '津波'),
        '土石流': ('debris_flow', 'debris_flow_safe', '土石流'),
    }.items():
        if shelter_bool_value(shelter, *aliases):
            values.add(disaster_name)
    return {str(value).strip() for value in values if str(value).strip()}


def alias_variants_for_key(key):
    """キー名の表記ゆれに対応する検索語の候補を返す"""
    aliases = {
        'pet_friendly': ['pet', 'pet_friendly', 'pet_allowed', 'pets_allowed', 'ペット', 'ペット可'],
        'pet': ['pet', 'pet_friendly', 'pet_allowed', 'pets_allowed', 'ペット', 'ペット可'],
        'pet_allowed': ['pet', 'pet_friendly', 'pet_allowed', 'pets_allowed', 'ペット', 'ペット可'],
        'pets_allowed': ['pet', 'pet_friendly', 'pet_allowed', 'pets_allowed', 'ペット', 'ペット可'],
        'barrier_free': ['barrier_free', 'barrierFree', 'バリアフリー'],
        'barrierFree': ['barrier_free', 'barrierFree', 'バリアフリー'],
        'has_preschool_children': ['has_preschool_children', 'preschool', 'preschool_children', '未就学児'],
        'preschool': ['has_preschool_children', 'preschool', 'preschool_children', '未就学児'],
        'preschool_children': ['has_preschool_children', 'preschool', 'preschool_children', '未就学児'],
        'parking_available': ['parking', 'parking_available', '駐車場'],
        'parking': ['parking', 'parking_available', '駐車場'],
        'senior_disability_support': ['senior_disability_support', 'elderly', 'elderly_consideration', '高齢者', '高齢者への配慮', '障害のある方への配慮'],
        'elderly': ['senior_disability_support', 'elderly', 'elderly_consideration', '高齢者', '高齢者への配慮'],
        'elderly_consideration': ['senior_disability_support', 'elderly', 'elderly_consideration', '高齢者', '高齢者への配慮'],
        'disability_consideration': ['disability', 'disability_consideration', '障害者', '障害のある方への配慮'],
        'disability': ['disability', 'disability_consideration', '障害者', '障害のある方への配慮'],
    }
    return aliases.get(str(key), [str(key)])


def shelter_search_text(shelter):
    """避難所の検索対象文字列を整形して返す"""
    text_parts = []
    for key, value in shelter.items():
        if value is None:
            continue
        if isinstance(value, bool):
            text_parts.append(str(key))
            if value:
                text_parts.extend(alias_variants_for_key(key))
            continue
        if isinstance(value, (list, tuple, set)):
            text_parts.extend(str(item) for item in value)
            continue
        text_parts.append(str(value))
    return ' '.join(text_parts).casefold()


def filter_shelters(district=None, criteria=None):
    """district と検索条件をまとめて避難所を絞り込む"""
    criteria = criteria or {}
    search_keywords = split_search_keywords(criteria.get('free_search', ''))

    requested_count = criteria.get('evacuee_count')
    try:
        requested_count = int(str(requested_count).strip()) if str(requested_count).strip() not in ('', None) else None
    except (TypeError, ValueError):
        requested_count = None
    if requested_count is not None and requested_count < 1:
        requested_count = None

    selected_disasters = []
    raw_disasters = criteria.get('disaster_types') or []
    if isinstance(raw_disasters, str):
        raw_disasters = [raw_disasters]
    for disaster in raw_disasters:
        if disaster not in (None, ''):
            selected_disasters.append(str(disaster))
    selected_disasters = [d.strip() for d in selected_disasters if d and d.strip()]

    results = []
    for shelter in shelters:
        if district and shelter.get('district') != district:
            continue

        if search_keywords:
            searchable_text = shelter_search_text(shelter)
            if not all(keyword in searchable_text for keyword in search_keywords):
                continue

        if has_criterion(criteria, 'pet_friendly', 'pet', 'pet_allowed', 'pets_allowed', 'ペット可') and not shelter_bool_value(shelter, 'pet_friendly', 'pet', 'pet_allowed', 'pets_allowed', 'ペット可'):
            continue
        if has_criterion(criteria, 'barrier_free', 'barrierFree', 'バリアフリー') and not shelter_bool_value(shelter, 'barrier_free', 'barrierFree', 'バリアフリー'):
            continue
        if has_criterion(criteria, 'has_preschool_children', 'preschool', 'preschool_children', '未就学児') and not shelter_bool_value(shelter, 'has_preschool_children', 'preschool', 'preschool_children', '未就学児'):
            continue
        capacity = shelter.get('capacity')
        try:
            capacity_value = int(capacity) if capacity not in (None, '', 'N/A') else 0
        except (TypeError, ValueError):
            capacity_value = 0
        if requested_count is not None and capacity_value < requested_count:
            continue
        if has_criterion(criteria, 'parking_available', 'parking', 'parking_available', '駐車場') and not shelter_bool_value(shelter, 'parking_available', 'parking', '駐車場'):
            continue

        if selected_disasters:
            shelter_disasters = shelter_disaster_set(shelter)
            normalized_required = []
            for disaster in selected_disasters:
                aliases = {str(disaster).strip()}
                if disaster == '地震':
                    aliases.update({'地震', 'earthquake'})
                elif disaster == '洪水':
                    aliases.update({'洪水', 'flood'})
                elif disaster == '土砂崩れ':
                    aliases.update({'土砂崩れ', 'landslide'})
                elif disaster == '津波':
                    aliases.update({'津波', 'tsunami'})
                elif disaster == '土石流':
                    aliases.update({'土石流', 'debris_flow'})
                elif disaster in {'earthquake', 'flood', 'landslide', 'tsunami', 'debris_flow'}:
                    aliases.add(str(disaster))
                    canonical = {
                        'earthquake': '地震',
                        'flood': '洪水',
                        'landslide': '土砂崩れ',
                        'tsunami': '津波',
                        'debris_flow': '土石流',
                    }
                    aliases.add(canonical[str(disaster)])
                normalized_required.append(aliases)
            if any(not aliases.intersection(shelter_disasters) for aliases in normalized_required):
                continue

        results.append(shelter)

    return results


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        if not name:
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所名を入力してください。'
            )

        if any(shelter.get('name') == name for shelter in shelters):
            return render_template(
                'shelter_register.html',
                error=True,
                message='同じ名前の避難所がすでに登録されています。'
            )

        next_id = max((shelter.get('id', 0) for shelter in shelters), default=0) + 1
        shelters.append({'id': next_id, 'name': name})
        save_shelters()
        return render_template(
            'shelter_register.html',
            success=True,
            message=f'避難所「{name}」を登録しました。'
        )

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html', shelters=shelters)

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    criteria = {
        'free_search': request.args.get('free_search', ''),
        'evacuee_count': request.args.get('evacuee_count', '').strip(),
        'pet_friendly': request.args.get('pet_friendly') == 'on',
        'pet': request.args.get('pet') == 'on',
        'pet_allowed': request.args.get('pet_allowed') == 'on',
        'pets_allowed': request.args.get('pets_allowed') == 'on',
        'barrier_free': request.args.get('barrier_free') == 'on',
        'barrierFree': request.args.get('barrierFree') == 'on',
        'has_preschool_children': request.args.get('has_preschool_children') == 'on',
        'preschool': request.args.get('preschool') == 'on',
        'preschool_children': request.args.get('preschool_children') == 'on',
        'parking_available': request.args.get('parking_available') == 'on',
        'parking': request.args.get('parking') == 'on',
        'senior_consideration': request.args.get('senior_consideration') == 'on',
        'elderly': request.args.get('elderly') == 'on',
        'elderly_consideration': request.args.get('elderly_consideration') == 'on',
        'disability_consideration': request.args.get('disability_consideration') == 'on',
        'disability': request.args.get('disability') == 'on',
        'senior_disability_support': request.args.get('senior_disability_support') == 'on',
        'disaster_types': request.args.getlist('disaster_type') or request.args.getlist('disaster_types')
    }
    results = filter_shelters(request.args.get('district'), criteria)
    return render_template('search_results.html', results=results, criteria=criteria)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = [i for i in instructions if i.get('target') == '住民']
    return render_template('board.html', instructions=resident_instructions)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
