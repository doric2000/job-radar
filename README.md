# Job Radar: בוט שמזהה משרות ג'וניור ראשון

> **English summary:** Job Radar is a Python bot that scans Israeli tech companies' job boards every 5 minutes and sends a Telegram alert when a junior role opens. It runs on an Oracle Cloud Always Free Ubuntu VM under a systemd timer, independent of any personal computer. It reads the public APIs of 20 kinds of job boards (Greenhouse, Lever, Ashby, Comeet, Workday, SmartRecruiters and others) plus LinkedIn's guest job search: 313 companies are listed and 243 of them have a verified board. Jobs are filtered by role, seniority, required years and location, in Hebrew and English. Reposts are caught with a MinHash signature of the description. Feedback comes back as emoji reactions on the alerts. Each run starts with `git pull`, so a push to `main` is a deploy. State lives in one JSON file mirrored to a `state` branch. GitHub Actions runs the 142 unit tests, a weekly board discovery and manual one-off scans. The bot does not apply to jobs.

הבוט סורק כל 5 דקות את לוחות המשרות הציבוריים של חברות ישראליות: סייבר, Backend ותשתיות, בנקים, תעשיות ביטחוניות וחברות רב־לאומיות. ברשימה יש 313 חברות, ול־243 מהן יש לוח משרות מאומת. בנוסף הוא מחפש בלינקדאין. הוא מסנן לפי הפרופיל שלך ושולח התראה בטלגרם **ברגע שמשרה חדשה מופיעה**.

הוא לא מגיש מועמדות. הוא מתריע ומסביר למה המשרה מתאימה, ואז אתה מגיש בקליק אחד.

## מה הוא מחפש (ברירות המחדל)

| נושא | הגדרה |
|---|---|
| תחומים | Backend, Systems, Full Stack, Frontend. אבטחת מידע וסייבר. אינטגרציה והטמעה של תוכנה, כולל AI, בלי אינטגרטורים של חומרה ואלקטרוניקה. DevOps ו־Cloud. QA ואוטומציה. |
| ותק | משרות שפונות במפורש למתחילים (Junior, Graduate, בוגר, Entry), או עד שנתיים ניסיון. משרה שלא מציינת ותק בכלל מתריעה עם האזהרה "ותק לא צוין", ואפשר לכבות את זה בהגדרות. |
| מיקום | ישראל (משרד או היברידי), עבודה מרחוק (עולמי, EMEA או ישראל), וחו״ל עם רילוקיישן. |
| סוג משרה | משרה מלאה והתמחות מובנית. משרות סטודנט ומשרות חלקיות לא מתריעות. |
| אישור ביטחוני | משרות כאלה **כן** מתריעות, עם התג 🔒. |
| הגשה | התראה בלבד, בלי הגשה אוטומטית. |

הכול ניתן לשינוי ב־`config.yaml`.

## איך הבוט נמנע מלהציף או לטעות

- **הבסיס הראשוני:** בסריקה הראשונה של חברה, המשרות הקיימות נרשמות בשקט. התראה יוצאת רק על משרה שתאריך הפרסום שלה במקור טרי, עד 48 שעות.
- **תאריכים מדויקים:** כל התראה מציינת מאיפה התאריך ומה סוגו: פורסמה, נוצרה, עודכנה, או דיוק של יום. עדכון לא מוצג כפרסום ראשון. משרה שמגיעה מהודעה בטלגרם מסומנת כ"ליד" שצריך לאמת במקור.
- **ותק נדרש מול יתרון:** "3 שנות ניסיון יתרון" לא פוסל, אבל "3+ שנות ניסיון" ברשימת הדרישות פוסל. הבדיקה עובדת גם על ניסוחים בעברית.
- **תקלה היא לא סגירה:** לוח שנכשל לא "סוגר" את המשרות שלו. ואם שליפת הפרטים של משרה נכשלה, הבוט מנסה שוב בריצה הבאה.
- **כפילויות:** משרה שמופיעה בשני מקורות מתריעה פעם אחת. גם משרה שפורסמה שוב בניסוח קצת שונה מזוהה, לפי חתימת MinHash של התיאור. פרסום חוזר מתריע שוב רק אם ההתראה הראשונה ישנה מ־14 יום.
- **דופק יומי:** כל בוקר מגיעה הודעה שקטה אחת, עם רשימת הלוחות שנכשלים ברצף.

## איפה הוא רץ

הסריקות רצות על מכונה וירטואלית של Ubuntu ב־Oracle Cloud, במסלול Always Free, ולא תלויות במחשב אישי.

- **`deploy/setup.sh`** מכין מכונה חדשה פעם אחת. הוא מתקין Python, משכפל את המאגר ויוצר venv. הוא יוצר קובץ סודות `~/.config/job-radar.env` בהרשאות 600. ואז הוא מגדיר שני קבצי systemd: service מסוג `oneshot`, וטיימר `OnCalendar=*:1/5` שמפעיל סריקה כל 5 דקות.
- **`deploy/run.sh`** הוא סריקה אחת. הסדר שלו:
  1. `git pull --ff-only`, כך ש־push ל־`main` נכנס לתוקף כבר בריצה הבאה.
  2. התקנה מחדש של התלויות אם `requirements.txt` השתנה.
  3. אימוץ ה־state מענף `state` אם ריצה ידנית ב־GitHub שינתה אותו.
  4. הסריקה עצמה.
  5. דחיפת ה־state חזרה לענף `state`.
- **GitHub Actions** מריץ את הבדיקות בכל push ואת הגילוי השבועי (`discover`). את `scan` מפעילים רק ידנית, לסיכום של משרות פתוחות או להתראה על משרה מסוימת. ככה שני סורקים לא רצים באותו זמן.

**למה לא GitHub Actions כמו בהתחלה:** עד 4.11.2026 הסריקה רצה ב־GitHub Actions. היו שלוש בעיות:
- התזמון של GitHub מתעכב, ולכן היה צריך cron חיצוני שיפעיל את ה־workflow.
- כ־290 ריצות ביום שלא קשורות לפיתוח הן שימוש ש־GitHub עלול לראות כניצול לרעה.
- חלק מהאתרים, למשל Check Point, חוסמים את הכתובות של השרתים של GitHub.

מהמכונה ב־Oracle כל אלה עובדים.

## הקמה (כ־30 דקות)

1. **בוט טלגרם:** בטלגרם כותבים ל־`@BotFather` את הפקודה `/newbot`, ושומרים את ה־token. אחר כך שולחים לבוט הודעה כלשהי, פותחים בדפדפן `https://api.telegram.org/bot<TOKEN>/getUpdates`, ומוצאים את `"chat":{"id":...}`.
2. **מכונה ב־Oracle Cloud:** Ubuntu 24.04 בצורה של Always Free (Ampere A1.Flex, או E2.1.Micro). בזמן היצירה מורידים זוג מפתחות SSH. אם האפשרות לכתובת IPv4 ציבורית נעולה, יוצרים קודם רשת עם VCN Wizard ובוחרים "Create VCN with Internet Connectivity", ואז יוצרים את המכונה בתוכה.
3. **התקנה:** מתחברים ב־SSH ומריצים:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/doric2000/job-radar/main/deploy/setup.sh | bash
   nano ~/.config/job-radar.env            # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
   bash ~/job-radar/deploy/run.sh          # סריקה אחת לבדיקה
   sudo systemctl enable --now job-radar.timer
   ```
4. **גיבוי ה־state ב־GitHub (לא חובה):** יוצרים fine-grained token שמוגבל למאגר הזה ולהרשאת Contents: read and write, ושמים אותו ב־`GH_PUSH_TOKEN` בקובץ הסודות. בלעדיו ה־state נשמר רק במכונה.
5. **הפעלות ידניות ב־GitHub:** ב־Settings → Secrets and variables → Actions מוסיפים `TELEGRAM_BOT_TOKEN` ו־`TELEGRAM_CHAT_ID`. ב־Settings → Actions → General נותנים ל־workflows הרשאת **Read and write**.
6. **גילוי לוחות משרות:** Actions → `discover` → Run workflow. הוא מזהה את מערכת הגיוס של כל חברה ומאמת אותה. בסוף נוצר `data/discovery_report.md` עם שלוש רשימות: נמצא, דורש בדיקה, לא נמצא. הגילוי רץ גם לבד פעם בשבוע.

## פקודות שימושיות

במכונה:

```bash
journalctl -u job-radar -n 50                 # הריצות האחרונות. כל ריצה מסתיימת בשורת סיכום
systemctl list-timers job-radar.timer         # מתי הסריקה הבאה
bash ~/job-radar/deploy/run.sh --all          # סריקה של כל החברות עכשיו, בלי לחכות לתור
```

מקומית:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests          # 142 בדיקות
python -m radar.discover --only wiz,cyera     # גילוי לחברות מסוימות
python -m radar.run --healthcheck             # בדיקת שליפה מול השירותים
python -m radar.run --dry-run --all           # מדפיס התראות בלי לשלוח ובלי לשמור
```

## מגבלות ידועות

- **לינקדאין:** החיפוש משתמש בממשק הציבורי של לינקדאין, בלי התחברות. אם הוא עונה 429 או 999, הבוט מפסיק לפנות ללינקדאין עד סוף אותה ריצה.
- **שינויים שקטים ב־API:** מערכת גיוס יכולה לשנות פורמט בלי הודעה. ב־Workday יש בדיקה ייעודית: אם הלוח מדווח על משרות אבל לא מחזיר אף אחת, זו נחשבת תקלה ולא "אפס משרות". בכל לוח אחר, כשל חוזר מופיע בדופק היומי.
- **חברות בלי לוח:** ל־70 מהחברות ברשימה אין עדיין לוח מאומת. לאתרי קריירה מותאמים אישית צריך סורק ייעודי (ראה `docs/SOURCES.md`).
- **המכונה החינמית:** Oracle עלולה לעצור מכונת Always Free שהמעבד, הרשת והזיכרון שלה מתחת ל־20% במשך 7 ימים. אם הבוט שותק, הודעת הבוקר לא מגיעה.

## הוספת חברה

מוסיפים שורה אחת ב־`companies.yaml` ומריצים `discover`. אם לחברה יש אתר קריירה מותאם אישית, כמו בנקים, תעשיות ביטחוניות, גוגל, מיקרוסופט או אמזון, היא תופיע ב־"not found". לחברות כאלה צריך סורק ייעודי (ראה `docs/SOURCES.md`).

## משוב ושיפור

המשוב הוא ריאקשן על ההתראה בטלגרם: 👍 ❤ 🔥 אומרים רלוונטי, ו־👎 💩 🤮 אומרים לא רלוונטי. אפשר גם להשיב (Reply) להתראה בטקסט חופשי, למשל "יותר מדי C#". הבוט קורא את המשוב בכל סריקה ושומר אותו ב־state. הודעות אחרות בצ'אט לא נשמרות, כי ה־state נמצא במאגר ציבורי.

פעמיים ביום סוכן Claude מתוזמן עובר על ההתראות ועל המשוב. הוא משנה כלל סינון רק כשיש ראיה ברורה. לכל שינוי הוא מוסיף בדיקה, ושום דבר לא נדחף אם בדיקה נכשלת. במקרים גבוליים הוא שואל ולא מחליט לבד.

משרות שכבר היו פתוחות כשחברה נוספה לא מתריעות, כדי לא להציף. כדי לקבל עליהן סיכום חד־פעמי לפי הכללים הנוכחיים: Actions → `scan` → Run workflow, עם `backlog`.

## הגשת מועמדות מהתראה

הבוט במאגר ציבורי, ולכן במכוון הוא לא מחזיק את קורות החיים שלך. כשמגיעה התראה מעניינת, שולחים את הקישור לשיחה עם Claude יחד עם קורות החיים, ומבקשים התאמה עובדתית של הקורות ומכתב קצר לפי הדרישות.

## מבנה

```
radar/run.py          לולאת הסריקה: תורות לפי tier, 12 threads, בסיס ראשוני, כפילויות, דופק יומי
radar/http.py         שכבת HTTP אחת לכל המקורות: timeout, ניסיונות חוזרים על 429/5xx, Retry-After, מרווח לכל שרת
radar/fetchers/       סורק לכל סוג של מערכת גיוס (20), וגם לינקדאין
radar/filters.py      סינון: תפקיד, בכירות, ותק נדרש מול יתרון, מיקום, אישור ביטחוני
radar/feedback.py     קריאת הריאקשנים והתגובות להתראות
radar/notify.py       שליחת ההתראות בטלגרם
radar/state.py        ה־state: מה נראה, מה נשלח, משוב
radar/discover.py     גילוי ואימות אוטומטי של לוחות משרות
radar/leads.py        קריאת ערוצי טלגרם ציבוריים (לידים)
deploy/               התקנה והרצה על המכונה (setup.sh, run.sh)
.github/workflows/    בדיקות, גילוי שבועי, סריקה ידנית
companies.yaml        רשימת החברות
docs/SOURCES.md       המקורות המורחבים והמחקר עליהם
```
