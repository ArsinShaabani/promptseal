# Social posts — PromptSeal v0.2 (2026-09-29)

> Ready-to-post drafts. X posts are under 280 chars. The dev.to article feeds
> directly into daily.dev (dev.to is a daily.dev source).

---

## X / Twitter — English (single post)

> You changed one word in your system prompt. Did you just break your app?
>
> Nobody knew. Now you know.
>
> 🦭 PromptSeal — regression testing for prompts, agents & models.
> seal → change model → diff → CI fails on regressions.
>
> github.com/ArsinShaabani/promptseal
> #LLM #OpenSource #AI #DevTools

## X / Twitter — English (thread, 3 posts)

1/ Your LLM app isn't broken. It's *drifting*. Every prompt tweak, model swap or
temperature change silently changes behavior. Unit tests can't catch it.
We built the missing tool. 🦭

2/ PromptSeal: describe the behavior you need in YAML (contains, regex, json_valid,
LLM-judge, latency, cost caps) → seal a baseline → let CI fail the build when
behavior regresses. Works with OpenAI, OpenRouter, Ollama, vLLM. Local-first, no server.

3/ It even records your real traffic through a local proxy (with PII redaction)
and turns it into eval cases. 40+ tests, MIT, bilingual docs (EN/FA).
⭐ github.com/ArsinShaabani/promptseal

## X / Twitter — فارسی

> یک کلمه تو system prompt عوض کردی. اپت رو خراب کردی؟
>
> قبلاً هیچ‌کس نمی‌دونست. حالا می‌دونه.
>
> 🦭 PromptSeal — تست رگرسیون برای پرامپت، ایجنت و مدل.
> seal کن → مدل رو عوض کن → diff بگیر → CI خودش می‌شکنه اگه رفتار عوض شده باشه.
>
> github.com/ArsinShaabani/promptseal
> #هوش_مصنوعی #OpenSource

---

## dev.to / daily.dev article (English — publish via dev.to API)

**Title:** I built a safety net for prompt changes — PromptSeal, regression testing for LLM apps

**Tags:** python, llm, devops, opensource

**Outline:**
1. The problem: silent behavioral drift (story: one-word system prompt change broke refund tone)
2. Why unit tests don't work for non-deterministic outputs
3. The core loop: describe → seal → change → diff (GIF)
4. 5-minute quickstart with the mock provider (no API key)
5. Recording real traffic with the local proxy + PII redaction
6. Model matrix: comparing gpt-4o vs llama3.1 on the same suite, cost included
7. CI gate with the official GitHub Action (code sample + PR screenshot)
8. What's next: pytest plugin, agent-trace assertions, suite registry
9. Links: repo, action repo, tutorial (EN + فارسی)

Call to action: star the repo, try the 30-second quickstart, tell us which
assertion you'd add.

## dev.to / daily.dev — مقاله فارسی (برای انتشار در وبلاگ شخصی یا نسخه دوم dev.to)

**عنوان:** برای پرامپت‌هام کمربند ایمنی ساختم — PromptSeal، تست رگرسیون برای اپ‌های LLM

**ساختار:**
1. مشکل: drift بی‌سروصدا — قصه‌ی خراب‌شدن لحن پشتیبانی با یک کلمه
2. چرا unit test برای خروجی‌های غیرقطعی جواب نمی‌ده
3. حلقه‌ی اصلی: تعریف → seal → تغییر → diff
4. شروع سریع ۵ دقیقه‌ای با provider ماک (بدون API key)
5. ضبط ترافیک واقعی با پراکسی لوکال + حذف خودکار PII
6. ماتریس مدل‌ها: gpt-4o در برابر llama3.1 روی همون سوییت، با محاسبه‌ی هزینه
7. گیت CI با اکشن رسمی گیت‌هاب
8. نقشه‌راه: پلاگین pytest، assertion روی ردپای عامل‌ها، رجیستری سوییت‌ها
9. لینک‌ها: ریپو، اکشن، آموزش فارسی و انگلیسی
