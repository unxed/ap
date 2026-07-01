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
    go tool pprof -text "$BINARY" "$PROFILE" | head -n 2
    echo "\`\`\`"
    echo ""

    echo "## 2. Топ-$LIMIT функций по собственному времени (Flat Time)"
    echo "Функции, в которых процессор провел больше всего времени непосредственно (без учета вызовов других функций):"
    echo "\`\`\`text"
    go tool pprof -text "$BINARY" "$PROFILE" | head -n $((LIMIT + 2))
    echo "\`\`\`"
    echo ""

    echo "## 3. Топ-$LIMIT функций по суммарному времени (Cumulative Time)"
    echo "Функции, выполнение которых (включая все вызванные ими подфункции) заняло больше всего времени:"
    echo "\`\`\`text"
    go tool pprof -text -cum "$BINARY" "$PROFILE" | head -n $((LIMIT + 2))
    echo "\`\`\`"
    echo ""

    echo "## 4. Детальный построчный анализ кода (pprof list)"
    echo "Ниже представлен построчный анализ для топ-$LIMIT функций (сортировка по Flat Time)."
    echo "Показывает, сколько времени ушло на конкретные строки исходного кода."
    echo ""

    # Получаем список имен топ-функций (исключаем заголовок pprof)
    FUNCTIONS=$(go tool pprof -text "$BINARY" "$PROFILE" | tail -n +3 | head -n "$LIMIT" | awk '{print $NF}')

    for FUNC in $FUNCTIONS; do
        echo "### Функция: $FUNC"
        echo "\`\`\`text"
        # Вызываем list для конкретной функции.
        # Перенаправляем stderr в stdout, чтобы ошибки отсутствия исходников тоже попадали в отчет.
        go tool pprof -list "$FUNC" "$BINARY" "$PROFILE" 2>&1 || echo "Не удалось получить исходный код для $FUNC"
        echo "\`\`\`"
        echo ""
    done

} > "$OUTPUT"

echo "Отчет успешно сохранен в файл: $OUTPUT"
