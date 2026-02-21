@echo off
cd /d C:\2026_Projet_Application\formation_app
call .venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000
pause

