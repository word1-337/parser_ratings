# RAExpert debt ratings parser

Парсер для страницы `https://raexpert.ru/ratings/debt_inst/`, который извлекает:

- кредитный рейтинг;
- дату рейтингового действия;
- название выпуска (эмиссии).

## Почему эта версия стабильнее

В отличие от прошлого варианта на Playwright, текущий скрипт:

- не зависит от внешних Python-пакетов;
- работает на стандартной библиотеке Python;
- умеет находить ссылки пагинации и собирать данные с нескольких страниц;
- проще дебажится и запускается в ограниченных окружениях.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> `requirements.txt` оставлен для совместимости workflow, но сторонних зависимостей нет.

## Запуск

```bash
python parser_raexpert_debt.py
```

По умолчанию результат сохраняется в `raexpert_debt_ratings.json`.

### Полезные опции

```bash
# Ограничить количество страниц
python parser_raexpert_debt.py --max-pages 3

# Сохранить CSV
python parser_raexpert_debt.py --csv raexpert_debt_ratings.csv

# Увеличить timeout
python parser_raexpert_debt.py --timeout 90
```

## Тесты

```bash
python -m unittest discover -s tests -v
```
