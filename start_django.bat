@echo off
cd /d C:\2026_Projet_Application\formation_app

call .venv\Scripts\activate

start cmd /k python manage.py runserver 0.0.0.0:8000

timeout /t 5 >nul

start "" http://127.0.0.1:8000/
