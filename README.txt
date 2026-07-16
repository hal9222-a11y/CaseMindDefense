PowerShell:

(אם יש שגיאת הרשאות: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned פעם אחת, ואז שוב)

CMD:

תדע שזה עבד כשתראה (.venv) בתחילת השורה. ואז מריצים את האפליקציה:

אבל שים לב — בשביל להריץ את האפליקציה אתה לא חייב להפעיל venv בכלל. אפשר פשוט להריץ בשורה אחת עם הנתיב המלא לפייתון של ה-venv:

ההפעלה (activate) נחוצה רק אם אתה רוצה לעבוד בתוך הסביבה (להתקין חבילות, להריץ כמה פקודות ברצף). ל-venv של ה-backend זה אותו דבר, רק עם backend\.venv בנתיב.

CMD
E:\WORK-FOLD\CaseMindDefense\desktop\.venv\Scripts\activate.bat

PowerShell

E:\WORK-FOLD\CaseMindDefense\desktop\.venv\Scripts\Activate.ps1




cd E:\WORK-FOLD\CaseMindDefense\desktop\casemind_desktop
python main.py


E:\WORK-FOLD\CaseMindDefense\desktop\.venv\Scripts\python.exe E:\WORK-FOLD\CaseMindDefense\desktop\casemind_desktop\main.py