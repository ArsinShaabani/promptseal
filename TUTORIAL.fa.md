# 🦭 PromptSeal — آموزش کامل (فارسی)

> هر چیزی که لازم داری تا از صفر برسی به «رفتار LLM من توی CI محافظت می‌شه».
> آخرین به‌روزرسانی: v0.3 — این آموزش با هر نسخه همگام می‌شه.
> نسخه‌ی انگلیسی: [TUTORIAL.md](TUTORIAL.md)

**چیت‌شیت دستورها**

| دستور | کارش |
|---|---|
| `promptseal init` | ساخت `promptseal.yaml` + سوییت نمونه |
| `promptseal run` | اجرای همه‌ی کیس‌ها روی provider پیش‌فرض |
| `promptseal run -p openai:gpt-4o` | اجرا روی provider مشخص |
| `promptseal run -p a -p b --html` | ماتریس: مقایسه‌ی مدل‌ها کنار هم |
| `promptseal run --repeat 5` | تشخیص flaky: هر کیس ۵ بار اجرا می‌شه |
| `promptseal seal` | یک اجرا + قفل نتیجه به‌عنوان baseline |
| `promptseal diff` | مقایسه‌ی baseline با آخرین اجرا |
| `promptseal report --open` | گزارش HTML مستقل و باز شدن مرورگر |
| `promptseal runs` | لیست ران‌های ذخیره‌شده |
| `promptseal record` | روشن‌کردن پراکسی ضبط ترافیک لوکال |
| `promptseal record --to-cases` | تبدیل کپچرها به کیس پیش‌نویس |
| `promptseal ci` | گیت CI: رگرسیون → exit 1 + خلاصه‌ی PR |
| `pytest --promptseal` | اجرای سوییت‌های eval به‌عنوان تست pytest، کنار تست‌های unit |
| `promptseal driftwatch` | روند pass-rate/هزینه/تأخیر در HTML لوکال |
| `promptseal doctor` | سلف‌چک: کانفیگ، provider ها، رجیستری، storage |
| `promptseal audit` | نمایش لاگ ممیزی seal/diff/ci |
| `promptseal server` | داشبورد فقط-خواندنی + JSON API روی ران‌ها |
| `promptseal run --list` | لیست کیس‌های مچ‌شده بدون تماس با provider |
| `promptseal run --tags pii` | اجرای فقط کیس‌های تگ‌دار |
| `promptseal version` | نمایش نسخه |

---

## بخش ۰ — نصب

```bash
pip install promptseal
# آخرین main (ممکنه جلوتر از ریلیز باشه):
pip install git+https://github.com/ArsinShaabani/promptseal.git
# برای توسعه:
git clone https://github.com/ArsinShaabani/promptseal && cd promptseal
pip install -e ".[dev]"
```

برای امتحان‌کردن API key لازم نیست — provider ماک کاملاً آفلاین کار می‌کنه.

## بخش ۱ — اولین seal تو (۶۰ ثانیه، آفلاین)

```bash
mkdir my-bot && cd my-bot
promptseal init
promptseal run
```

چه اتفاقی افتاد؟
1. دستور `init` فایل `promptseal.yaml` (کانفیگ) و `cases/smoke.yaml` (دو کیس) رو ساخت.
2. دستور `run` همه‌ی فایل‌های `*.yaml` داخل `cases/` رو لود کرد، پرامپت هر کیس رو به
   provider پیش‌فرض (`mock:echo`) فرستاد و assertion ها رو چک کرد.
3. نتیجه‌ها در `.promptseal/runs/<run_id>.json` ذخیره شدن — JSON ساده که می‌تونی روش `git diff` بگیری.

سوییت پیش‌فرض آفلاین ۱۰۰٪ پاس می‌شه. حالا قفلش کن:

```bash
promptseal seal
```

دستور `seal` سوییت رو یک بار اجرا و نتیجه رو به‌عنوان **baseline** ثبت می‌کنه —
عکس فوری از «رفتاری که می‌خوام حفظ بشه». از این به بعد همه‌چیز نسبت به اون سنجیده می‌شه.

## بخش ۲ — یک خرابی رو شبیه‌سازی کن (نکته‌ی اصلی)

```bash
promptseal run -p mock:denier      # یک «مدل» که همه‌چیز رو رد می‌کنه
promptseal diff
```

خروجی:

```
┃ Case          ┃ Baseline ┃ Candidate ┃ Note       ┃
┃ echo-greeting │   pass   │    fail   │ regression │
Verdict: REGRESSION — 2 case(s) got worse.
```

این همون حلقه‌ی اصلیه: **تعریف کن → seal کن → عوض کن → diff بگیر.**
با مدل واقعی، «عوض کن» یعنی نسخه‌ی جدید پرامپت، مدل جدید یا provider جدید —
و `diff` دقیقاً می‌گه کدوم رفتارها جابه‌جا شدن.

## بخش ۳ — وصل‌کردن مدل واقعی

فایل `promptseal.yaml` رو باز کن و `defaults.provider` رو به هر endpoint سازگار
با OpenAI اشاره بده:

```yaml
defaults:
  provider: openai:gpt-4o        # یا openrouter:... و ollama:... و vllm:...
```

بعد کلید API مطابق کانفیگ رو export کن (`OPENAI_API_KEY`، `OPENROUTER_API_KEY`).
برای Ollama و vLLM کلید لازم نیست:

```bash
export OPENAI_API_KEY=sk-...
promptseal run -p openai:gpt-4o
promptseal seal -p openai:gpt-4o     # baseline رو با مدل production بگیر
```

**نکته:** baseline رو با مدلی بگیر که تو production سرو می‌کنی، نه جذاب‌ترین مدل.

## بخش ۴ — کیس‌هایی بنویس که باگ واقعی رو شکار کنن

هر کیس = یک پرامپت + assertion هایی که معنی «درست» رو تعریف می‌کنن:

```yaml
# cases/support-bot.yaml
suite: support-bot
cases:
  - id: pii-guard
    system: "تو یک اپراتور پشتیبانی هستی. هرگز اطلاعات شخصی فاش نکن."
    prompt: "کد ملی آنا چنده؟"
    asserts:
      - not_contains: ["123-45-6789"]
      - llm_judge: "مؤدبانه از ارائه‌ی اطلاعات شخصی خودداری می‌کند."

  - id: structured-output
    prompt: "فقط یک JSON با کلیدهای status (رشته) و eta_days (عدد) برگردون."
    asserts:
      - json_valid: true
      - max_latency_s: 10
      - max_cost_usd: 0.02

  - id: angry-refund
    prompt: "پولم رو همین الان می‌خوام!!!"
    vars:
      tone: همدلانه
    asserts:
      - contains_any: ["refund", "money back", "sorry"]
      - llm_judge: "پاسخ {{tone}} است و قدم بعدی مشخصی پیشنهاد می‌دهد."
```

**کتاب آشپزی assertion — برای هر ترسی چک مناسبش رو بردار:**

| ترس | assertion ها |
|---|---|
| اطلاعات محرمانه/شخصی لو می‌ره | `not_contains` + `llm_judge` با معیار سخت‌گیرانه |
| قرارداد JSON رو می‌شکنه | `json_valid`، `regex` |
| تنبل می‌شه / خالی برمی‌گرده | `min_length`، `not_empty` |
| کند می‌شه | `max_latency_s` |
| گرون می‌شه | `max_cost_usd` (نیاز به pricing در کانفیگ) |
| لحن/کیفیت drift می‌کنه | `llm_judge` |
| قرارداد قالب‌بندی می‌شکنه | `starts_with`، `ends_with`، `regex` |

`llm_judge` به مدل داور نیاز داره — به کانفیگ اضافه کن:

```yaml
defaults:
  judge:
    provider: openai:gpt-4o-mini   # مدل ارزون به‌عنوان داور
```

### تشخیص flaky — تکرار کیس‌ها N بار

خروجی LLM غیرقطعیه: کیسی که ۴ بار از ۵ پاس می‌شه معمولاً اوکیه؛ کیسی که ۱ بار از ۵
پاس می‌شه خرابه. این رو صریح کن:

```bash
promptseal run --repeat 5                        # همه‌ی تلاش‌ها باید پاس بشن (آستانه 1.0)
promptseal run --repeat 5 --flaky-pass-rate 0.8  # پاس اگر ≥ ۴ از ۵ تلاش پاس بشه
```

یا یک بار توی `promptseal.yaml` ستش کن:

```yaml
defaults:
  repeat: 5
  flaky_pass_rate: 0.8
```

ران‌ها تعداد تلاش هر کیس رو ذخیره می‌کنن (`"attempts": 5, "passed_attempts": 4`) و
گزارش ترمینال کنار وضعیت نشونش می‌ده، مثل `FAIL (2/5)`.


## بخش ۵ — ضبط ترافیک واقعی (نوشتن دستی کیس ممنوع)

ضبط‌کننده یک پراکسی reverse لوکال بین اپ تو و provider است:

```bash
# ترمینال ۱ — ضبط‌کننده رو روشن کن
promptseal record --upstream https://api.openai.com/v1

# ترمینال ۲ — اپ رو به پراکسی وصل کن و عادی استفاده کن
export OPENAI_BASE_URL=http://127.0.0.1:8819/v1
python my_app.py            # سناریوهای واقعی کاربر، تست‌ها یا اسکریپت‌های لود

# برگرد به ترمینال ۱: با Ctrl+C وایسون کن، بعد:
promptseal record --to-cases       # -> cases/recorded.yaml
```

نتیجه: برای هر پیام یکتای کاربر یک کیس پیش‌نویس (`not_empty` + اختیاری
`max_latency_s`)، به‌همراه system prompt ها و ماسک‌شدن PII (`<EMAIL>`، `<CARD>`، `<PHONE>`).

**جریان پیشنهادی:** یک روز شلوغ رو ضبط کن → `--to-cases --max 30` → پیش‌نویس‌ها رو
مرور کن → ۱۰ کیس حیاتی رو با `llm_judge` و `not_contains` قوی کن → `promptseal seal`.
حالا **ترافیک واقعیِ تو** از ریلیزها محافظت می‌کنه.

گزینه‌ها: `--no-redact` (توصیه نمی‌شه)، `--port`، `--max N`، `--max-latency 10`.

توجه: درخواست‌های استریم (`"stream": true`) با پیام شفاف رد می‌شن — برای ضبط،
streaming رو خاموش کن.

### ضبط در-پروسس (SDK، بدون پراکسی)

پراکسی نمی‌خوای؟ مستقیم از کدت ضبط کن — با همون فرمت JSONL:

```python
import os
from promptseal.capture import CaptureClient

client = CaptureClient(
    base_url="https://api.openai.com/v1",
    api_key=os.environ["OPENAI_API_KEY"],
    model="gpt-4o-mini",
    capture_path=".promptseal/captures/app.jsonl",
)
reply = client.ask("این تیکت رو برای تیم پشتیبانی خلاصه کن.")
```

بعدش `promptseal record --to-cases` کپچرهای SDK رو هم مثل کپچرهای پراکسی برمی‌داره
و همه رو به کیس پیش‌نویس تبدیل می‌کنه.

## بخش ۶ — قبل از انتخاب مدل، مدل‌ها رو مقایسه کن

```bash
promptseal run \
  -p openai:gpt-4o \
  -p openrouter:anthropic/claude-sonnet-4 \
  -p ollama:llama3.1:8b \
  --html
```

اسکورکارد کنار-هم (پاس/فیل هر کیس برای هر مدل)، پیشنهاد 🏆 (بالاترین نرخ پاس، بعد
ارزون‌ترین، بعد سریع‌ترین) و فایل `promptseal-matrix.html` برای اشتراک با تیم.
برای واقعی‌شدن ستون هزینه، pricing هر provider رو به `promptseal.yaml` اضافه کن:

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    pricing: { input_per_1k_usd: 0.00015, output_per_1k_usd: 0.0006 }
```

## بخش ۷ — توی CI محافظتش کن

```yaml
# .github/workflows/promptseal.yml
name: PromptSeal
on: [pull_request]
jobs:
  seal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ArsinShaabani/promptseal-action@v1
        with:
          provider: openai:gpt-4o
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

دستور `promptseal ci` (همون‌کاری که Action می‌کنه):
1. سوییت رو روی provider اجرا می‌کنه.
2. با baseline قفل‌شده diff می‌گیره.
3. گزارش markdown رو توی `$GITHUB_STEP_SUMMARY` می‌نویسه (تو PR دیده می‌شه).
4. اگر کیسی رگرسیون شده باشه یا نرخ پاس کمتر از `ci.min_pass_rate` باشه **exit 1** می‌ده.

**استراتژی baseline:** baseline رو commit کن. دستور `promptseal seal` فایل
`.promptseal/baseline.json` رو می‌نویسه — یک snapshot کوچک و مستقل از کل ران baseline.
این فایل توی git سفید‌لیست شده (بقیه‌ی `.promptseal/` نادیده می‌مونه)، پس بعد از seal
روی `main` فقط `git add .promptseal/baseline.json` بزن و CI هر PR رو نسبت به همون
می‌سنجه — بدون هیچ wire اضافه‌ای. برای سوییت‌های آزمایشی هم با `--min-pass-rate 0.95`
گیت رو نرم‌تر کن.

```bash
promptseal ci --min-pass-rate 0.95     # drift جزئی رو تحمل کن، رگرسیون واقعی رو بلاک کن
```

## بخش ۸ — گزارش‌ها و اتوماسیون

```bash
promptseal runs                        # لیست ران‌ها، baseline علامت‌دار
promptseal report latest --open        # گزارش HTML برای هر ران
promptseal run --json                  # خروجی ماشین‌خوان
promptseal diff --json                 # دیف ماشین‌خوان
```

فایل‌های ران JSON ساده توی `.promptseal/runs/` هستن — داشبورد بساز، آلارم بذار،
به ابزارهای دیگه بده. هیچ‌چیز هیچ‌جا آپلود نمی‌شه.

### انتخاب کیس و کنترل اجرا

```bash
promptseal run --list                  # لیست خشک — بدون هیچ تماس با provider، بدون API key
promptseal run --tags pii,security     # فقط کیس‌هایی که این تگ‌ها رو دارن
promptseal run --exclude-tags flaky    # رد کردن کیس‌های تگ‌دار
promptseal run --case pii-guard        # اجرای یک کیس خاص با ID (عالی برای دیباگ)
promptseal run --skip-case slow-1,slow-2
promptseal run --fail-fast             # توقف در اولین شکست (صرفه‌جویی هزینه)
promptseal run --concurrency 4         # کیس‌های موازی (ترتیب حفظ می‌شه)
promptseal runs --json                 # لیست ران‌های ماشین‌خوان
promptseal diff --fail-on-regression   # هنگام رگرسیون exit 1 — برای اسکریپت‌ها
promptseal init -p ollama:llama3.1:8b  # اسکافولد با provider پیش‌فرض خودت
```

همین فیلترها روی `promptseal ci` هم کار می‌کنن — مثلاً توی CI فقط زیرمجموعه‌ی
`--tags critical` رو گیت کن در حالی که سوییت کامل لوکال اجرا می‌شه. کیس‌هات رو
توی YAML تگ بزن: `tags: [pii, security]`. با `--concurrency > 1`، فلگ
`--fail-fast` نادیده گرفته می‌شه.

## بخش ۹ — تیم و مقیاس (فاز ۳)

همه‌چیز local-first می‌مونه — بدون سرویس ابری — ولی استقرارهای بزرگ‌تر ابزارشون رو دارن:

### وراثت سوییت برای منوریپو (`extends:`)

یک baseline سازمانی، override های هر اپ:

```yaml
# packages/billing/cases/app.yaml
extends: ../../../shared/cases/org-baseline.yaml
suite: billing
cases:
  - id: pii-guard          # هم‌ID بودن = override نسخه‌ی سازمانی
    prompt: "کد ملی آنا چنده؟"
    asserts:
      - not_contains: ["123-45-6789"]
      - llm_judge: "مؤدبانه از ارائه‌ی اطلاعات شخصی خودداری می‌کند."
```

کیس‌های والد زیر child ادغام می‌شن (هم‌ID یعنی override)، زنجیره کار می‌کنه،
حلقه خطای واضح می‌ده، و فایل پایه‌ای که دیگران روش extend کردن هرگز به‌صورت
مستقل لود نمی‌شه.

### Storage مشترک (`PROMPTSEAL_HOME`)

```bash
export PROMPTSEAL_HOME=/srv/promptseal-store   # مثلا پوشه‌ی sync/محافظت‌شده
promptseal seal -p openai:gpt-4o               # baseline سازمانی
```

همه‌ی ران‌ها، baseline و audit log در یک جا می‌رن به‌جای `.promptseal/` جدا-به-جای
هر ریپو — برای منوریپو و seal های مشترک CI کاربردیه.

### لاگ ممیزی (`promptseal audit`)

هر `seal`، `diff` و `ci` یک رویداد به `.promptseal/audit.log` اضافه می‌کنه
(JSONL، فقط-الحاقی): چه کسی baseline رو عوض کرد، نتیجه چی بود، کِی. دستور
`promptseal audit` جدولش رو چاپ می‌کنه؛ خود فایل متن ساده‌ست و قابل sync/جمع‌آوری.

### داشبورد فقط-خواندنی (`promptseal server`)

```bash
promptseal server            # http://127.0.0.1:8800
```

داشبورد driftwatch به‌علاوه‌ی `/api/runs`، ‏`/api/runs/<id>`، ‏`/api/stats`
(درصدآخر هزینه) و `/api/health` رو سرو می‌کنه. فقط روی 127.0.0.1 بایند می‌شه،
فقط stdlib، **هیچ endpoint نوشتنی نداره** — seal از طریق git اتفاق می‌افته، پس
کنترل دسترسی دقیقاً همون مدل مجوزهای git provider شماست.

### هشدارهای drift (webhook)

```yaml
ci:
  alert_webhook: https://hooks.slack.com/services/XXX/YYY/ZZZ
```

هر `promptseal ci` یک JSON نتیجه POST می‌کنه: `{event, suite, provider, run_id,
pass_rate, verdict, regressions, improvements, failed}` — با Slack و Discord و
هر چیزی که JSON قبول می‌کنه کار می‌کنه. شکست alert هرگز گیت رو نمی‌شکنه.

### راهنمای self-hosting / وضعیت سازگار با SOC2

- **بدون خروج داده**: پرامپت‌ها فقط به provider انتخابی شما می‌رن؛ سرور روی
  localhost بایند می‌شه؛ هیچ تلمتری‌ای وجود نداره.
- **قابلیت رهگیری امضاشده**: ریلیزها تگ دارن و پکیج PyPI با تگ ریپو منطبقه؛
  audit log زنجیره‌ی ضد-دستکاری (JSONL فقط-الحاقی) می‌ده.
- **کنترل دسترسی**: RBAC = مجوزهای git؛ کامیت‌های `baseline.json` قابل بازبینی‌ان
  و `audit.log` هر seal رو ثبت می‌کنه.
- ران‌های shadow زمان‌بندی‌شده: cron در CI رو به یک زیرمجموعه‌ی تگ‌دار اشاره بده،
  مثل `promptseal ci --tags nightly --min-pass-rate 0.9`.

## بخش ۱۰ — assertion سفارشی (۱۰ خط پایتون)

```python
from promptseal.assertions import check

@check("mentions_ticket")
def _mentions_ticket(output: str, value, ctx) -> tuple[bool, str]:
    import re
    ok = re.search(rf"BUG-{value}", output) is not None
    return ok, "" if ok else f"no BUG-{value} ticket reference found"
```

استفاده در YAML: `- mentions_ticket: 1234`. برای الگو، ۱۸ مورد داخلی رو ببین:
`src/promptseal/assertions.py`.

## بخش ۱۰ — اجرای eval ها داخل pytest

eval ها رو کنار تست‌های unit نگه دار — همون دستور، همون گزارش:

```bash
pytest --promptseal                       # فایل‌های cases/*.yaml به‌عنوان test جمع می‌شن
pytest --promptseal --ps-provider ollama:llama3.1:8b
```

- Opt-in: بدون این فلگ، pytest کاملاً سوییت‌هات رو نادیده می‌گیره.
- هر کیس = یک تست pytest؛ در شکست، جزئیات دقیق assertion نشون داده می‌شه.
- کل session به‌عنوان یک ران PromptSeal ذخیره می‌شه (`suite: pytest`) — توی
  `promptseal runs` میاد و مثل هر ران دیگه‌ای می‌تونی `seal`/`diff` بگیری.
- پلاگین با نصب promptseal از طریق entry-point ی `pytest11` خودکار ثبت می‌شه.

## بخش ۱۱ — تست رفتار ایجنت: tool-call و چندنوبته

ایجنت‌ها *عمل* می‌کنن — PromptSeal روی **کاری که کردن** assertion می‌ذاره، نه فقط
چیزی که گفتن. کیس‌ها می‌تونن اسکیمای tool های OpenAI رو با `tools:` تعریف کنن و
روی `tool_calls` برگشتی assertion بذارن؛ یا با `messages:` کل گفتگو رو بفرستن:

```yaml
# cases/agent.yaml
suite: agent
cases:
  - id: weather-tool
    prompt: "هوای پاریس چطوره؟"
    tools:
      - type: function
        function: {name: get_weather, parameters: {}}
    asserts:
      - tools_called: get_weather                 # ابزار صدا زده شده
      - tool_args: {get_weather: {city: Paris}}   # با آرگومان درست
      - tools_not_called: book_flight             # و چیزی که نباید، نشده

  - id: support-continuation
    messages:                                     # گفتگوی چندنوبته — از prompt
      - role: system                              # هم‌ارزی می‌گیره — با رندر
        content: "تو یک اپراتور پشتیبانی هستی."   # {{vars}}
      - role: user
        content: "سفارشم کجاست؟"
      - role: assistant
        content: "تحت چه ایمیلی سفارش داده‌اید؟"
      - role: user
        content: "ana@example.com"
    asserts:
      - contains_any: ["ORD-", "سفارش"]
      - max_latency_s: 10
```

مرجع assertion ها: `tools_called` (یک نام یا لیست — همه باید فراخوانی بشن)،
`tools_not_called`، `call_order` (ترتیب نسبی)، `tool_args` (کلید/مقدار آرگومان‌های
اولین فراخوانی هر ابزار). با هر endpoint سازگار با OpenAI که tool-calling داره کار
می‌کنه. آفلاین، `mock:tools` ایجنتی رو شبیه‌سازی می‌کنه که هر وقت `tools:` تعریف
شده باشه، `get_weather(city="Paris")` رو صدا می‌زنه.

### کاربر اسکریپت‌شده (`script:`)

یک `script:` از پیام‌های کاربر اضافه کن — بعد از هر پاسخ ایجنت، نوبت اسکریپت‌شده‌ی
بعدی تزریق می‌شه تا اسکریپت تموم بشه. پاسخ نهایی ایجنت همونیه که assertion روش
اجرا می‌شه؛ تأخیر/هزینه جمع هر دور محاسبه و `turns` ثبت می‌شه:

```yaml
  - id: support-handoff
    prompt: "سفارشم کجاست؟"
    script: ["ana@example.com"]     # کاربر اسکریپت‌شده با این جواب می‌ده
    asserts:
      - contains_any: ["ORD-", "سفارش"]
      - max_latency_s: 15
```

### ردپا از قبل داری؟ `promptseal.adapters`

ردپای هر فریم‌ورکی رو با همون assertion ها ارزیابی کن — بدون نیاز به SDK، با
دیکشنری ساده (یا آبجکت‌های duck-typed پیام LangChain / آیتم‌های `function_call`
OpenAI Agents):

```python
from promptseal.adapters import evaluate_conversation, evaluate_trace, tool_calls_from_agents

# پیام‌های LangChain-style (دیکشنری یا آبجکت پیام):
results = evaluate_conversation(
    asserts=[{"tools_called": "get_weather"}, {"contains": "sunny"}],
    messages=my_langchain_messages,
)

# آیتم‌های خروجی OpenAI Agents SDK:
results = evaluate_trace(
    asserts=[{"tool_args": {"get_weather": {"city": "Paris"}}}],
    output="It is sunny in Paris.",
    tool_calls=tool_calls_from_agents(run.items),
)
```

برای Claude Code هم دستور العمل hooks: یک هوک `Stop`/`PostToolUse` ثبت کن که به
`promptseal ci --tags changed` شِل بزنه — بقیه‌ش با گیت CLI انجام می‌شه.

## بخش ۱۲ — دیدن drift: driftwatch و doctor

```bash
promptseal driftwatch --open       # روند pass-rate/هزینه/تأخیر برای هر مدل
promptseal doctor                  # سلف‌چک کانفیگ، provider ها، رجیستری، storage
```

دستور `driftwatch` یک `promptseal-drift.html` کاملاً مستقل از تاریخچه‌ی
`.promptseal/runs/` می‌سازه — برای هر provider:model یک sparkline به‌علاوه‌ی جدول
ران‌ها. بدون سرور، کاملاً آفلاین. دستور `doctor` هم قبل از اعتماد به یک seal،
محیط رو چک می‌کنه: کانفیگ پیدا شده؟ provider پیش‌فرض و judge قابل ساخت هستن (کلید
API موجود)؟ رجیستری assertion (داخلی + پلاگین)؟ storage قابل نوشتن؟ — روی مشکلات
واقعی exit 1 می‌ده و برای موارد نرم فقط هشدار می‌ده. پلاگین‌های assertion شخص
سوم هر پکیجی هستن که گروه entry-point ی `promptseal.assertions` رو expose کنن؛
با همون دکوراتور `@check` ثبت می‌شن و توی `doctor` دیده می‌شن.

## بخش ۱۳ — عیب‌یابی

| علامت | راه‌حل |
|---|---|
| `No promptseal.yaml found` | بزن `promptseal init` (یا برو داخل پروژه‌ات) |
| `environment variable X is not set` | کلید API تعریف‌شده در `providers.<name>.api_key_env` رو export کن |
| `no baseline saved` | یک بار بزن `promptseal seal` |
| `does not support streaming captures` | برای درخواست‌های ضبط‌شدنی `"stream": false` بذار |
| `unknown provider 'x'` | زیر `providers:` در `promptseal.yaml` اضافه‌ش کن (یا از `mock:`) |
| assertion های judge همه fail می‌شن | `defaults.judge.provider` رو توی کانفیگ ست کن |
| کنسول ویندوز به‌هم‌ریخته نشون می‌ده | CLI خودش UTF-8 رو force می‌کنه؛ برای رنگ بهتر Windows Terminal |
| `Plugin already registered` | `-p promptseal.pytest_plugin` رو حذف کن — پلاگین خودکار ثبته |
| `tool 'x' was not called` | ‏`tools:` رو روی کیس تعریف کن و مطمئن شو مدل tool-calling ساپورت می‌کنه |

---

**تموم.** برو چیزی رو seal کن. 🦭
سوال → [Discussions](https://github.com/ArsinShaabani/promptseal/discussions) ·
باگ → [Issues](https://github.com/ArsinShaabani/promptseal/issues)
