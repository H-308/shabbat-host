# Shabbat Host 🕯️

סוכן לאירוח ארוחות שישי שזוכר אורחים, מגבלות תזונה והעדפות, בונה תפריט כשר שמתאים לכולם, ובודק זמני כניסת שבת ומזג אוויר. הוא בנוי פעמיים: על ה-Messages API הגולמי (`API/`), ועל Claude Agent SDK (`SDK/`).

```
shabbat-host-hadasa/
  shared/          קוד הדומיין, משותף לשתי הגרסאות
    tools_spec.py    7 כלים (כולל shabbat_info החיצוני), פלט קומפקטי
    domain.py        כשרות, מגבלות אורחים, זמני הכנה
    external.py      Hebcal + Open-Meteo, בלי מפתח
    store.py         guests.json / menus.json / tool_log.jsonl
    checks.py        הבדיקות של scenario.json, על המצב שנשמר
    runner.py loc.py report.py config.py prompt.py
    data/recipes.json
  API/             main.py  agent.py  harness/{loop,tools,history,memory,context,compaction,caching,tokens}.py
  SDK/             main.py  agent.py  tools.py   (כל שורה מחליפה מסומנת # replaces: <part>)
  tests/           30 בדיקות offline: client מדומה, SDK client מדומה, fetch מדומה
  scenario.json    7 פניות בשני סשנים, 18 בדיקות
  results/         api.json  sdk.json (נוצרים בריצה)
  REPORT.md
```

הוראות ההרצה וכל הניתוח נמצאים ב-[REPORT.md](REPORT.md).
