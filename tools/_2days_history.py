#!/bin/python3
import os
import subprocess
from datetime import datetime, timedelta

def run_command(command):
    """Выполняет консольную команду и возвращает результат."""
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Ошибка при выполнении: {command}\n{result.stderr}")
        return None
    return result.stdout

def main():
    # 1. Подготовка папки
    output_dir = "_git_history"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Создана папка: {output_dir}")

    # 2. Вычисляем дату "вчера 00:00" для фильтрации
    # Это захватит весь вчерашний и весь сегодняшний календарные дни
    yesterday_midnight = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    since_date = yesterday_midnight.strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"Сбор коммитов начиная с: {since_date}")

    # 3. Сохраняем общий лог (git_log.txt)
    # Используем --since, чтобы ограничить выборку
    log_cmd = f'git log --since="{since_date}" --pretty=medium'
    git_log_content = run_command(log_cmd)
    
    if not git_log_content or git_log_content.strip() == "":
        print("За указанный период (вчера и сегодня) коммитов не найдено.")
        return

    with open(os.path.join(output_dir, "git_log.txt"), "w", encoding="utf-8") as f:
        f.write(git_log_content)
    print("Сохранен файл git_log.txt")

    # 4. Получаем список хэшей всех коммитов за этот период
    hash_list_cmd = f'git log --since="{since_date}" --format="%H"'
    hashes = run_command(hash_list_cmd).strip().split('\n')

    # 5. Сохраняем diff для каждого коммита
    for commit_hash in hashes:
        if not commit_hash:
            continue
            
        diff_cmd = f'git show {commit_hash}'
        diff_content = run_command(diff_cmd)
        
        if diff_content:
            filename = f"{commit_hash}.diff"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(diff_content)
            print(f"Сохранен diff: {filename}")

    print("\nГотово! Все файлы в папке _git_history")

if __name__ == "__main__":
    main()