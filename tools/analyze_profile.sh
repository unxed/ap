#!/usr/bin/env bash
set -euo pipefail

# Проверка аргументов
if [ "$#" -lt 2 ]; then
    echo "Использование: $0 <путь_к_бинарнику> <путь_к_cpu.prof> [имя_отчета.md]"
    exit 1
fi

BINARY=$1
PROFILE=$2
OUTPUT=${3:-"profile_report.md"}
LIMIT=10 # Количество самых медленных функций для детального анализа

echo "Сбор данных и генерация отчета в $OUTPUT..."

{
    echo "# Отчет о производительности Go CPU Profile"
    echo "Дата генерации: $(date)"
    echo "Версия Go: $(go version 2>/dev/null || echo 'Не найдена')"
    echo "Бинарный файл: $BINARY"
    echo "Профиль: $PROFILE"
    echo ""

    echo "## 1. Общая сводка (Summary)"
    echo "Общее время работы и количество сэмплов:"
    echo "\`\`\`text"
    # Сохраняем весь вывод во временную переменную, чтобы избежать SIGPIPE при фильтрации
    PPROF_TEXT=$(go tool pprof -text "$BINARY" "$PROFILE")
    echo "$PPROF_TEXT" | head -n 2
    echo "\`\`\`"
    echo ""

    echo "## 2. Топ-$LIMIT функций по собственному времени (Flat Time)"
    echo "Функции, в которых процессор провел больше всего времени непосредственно:"
    echo "\`\`\`text"
    echo "$PPROF_TEXT" | head -n $((LIMIT + 7))
    echo "\`\`\`"
    echo ""

    echo "## 3. Top-$LIMIT функций по суммарному времени (Cumulative Time)"
    echo "Функции, выполнение которых (включая все подфункции) заняло больше всего времени:"
    echo "\`\`\`text"
    go tool pprof -text -cum "$BINARY" "$PROFILE" | head -n $((LIMIT + 7))
    echo "\`\`\`"
    echo ""

    echo "## 4. Детальный построчный анализ кода (pprof list)"
    echo "Ниже представлен построчный анализ для функций (сортировка по Flat Time)."
    echo ""

    # Извлекаем имена функций, фильтруя только строки, начинающиеся с цифр (данные профилирования).
    # Это позволяет надежно пропустить заголовки pprof без использования head в конвейере.
    FUNCTIONS=$(echo "$PPROF_TEXT" | awk -v limit="$LIMIT" '/^[[:space:]]*[0-9]/ { count++; if (count <= limit) print $NF }')

    # Отключаем globbing (генерацию имен файлов по маске), так как имена функций содержат символы '*'
    set -f
    for FUNC in $FUNCTIONS; do
        echo "### Функция: $FUNC"
        echo "\`\`\`text"
        
        # Экранируем символы регулярных выражений (. * ( ) [ ] + ? ^ $ |), чтобы pprof корректно их обработал
        CLEAN_FUNC=$(echo "$FUNC" | sed 's/[.()\[\]*+?^$\|]/\\&/g')
        
        # Запускаем list. Если исходники недоступны, pprof выведет ошибку, но скрипт продолжит работу.
        go tool pprof -list "$CLEAN_FUNC" "$BINARY" "$PROFILE" 2>&1 || echo "Не удалось выполнить list для $FUNC"
        echo "\`\`\`"
        echo ""
    done
    set +f

} > "$OUTPUT"

echo "Отчет успешно сохранен в файл: $OUTPUT"
