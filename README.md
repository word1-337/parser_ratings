# RAExpert debt ratings parser

Парсер для `https://raexpert.ru/ratings/debt_inst/`, который извлекает:

- эмиссию (`issue`);
- эмитента (`issuer`);
- кредитный рейтинг (`rating`);
- дату рейтингового действия (`date`);
- ссылку на **последний актуальный на дату запуска** пресс-релиз агентства по эмитенту (`press_release_url`).

## Особенности

- стандартная библиотека Python (без внешних зависимостей);
- retry + timeout при загрузке страниц;
- поддержка пагинации (`PAGEN_*` / `page=`);
- автоматическая нормализация разных вариантов дефиса/минуса в рейтингах;
- сохранение в JSON и опционально в CSV.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> `requirements.txt` оставлен для совместимости workflow, сторонних пакетов не требуется.

## Запуск

```bash
python parser_raexpert_debt.py
```

### Опции

```bash
python parser_raexpert_debt.py --max-pages 3
python parser_raexpert_debt.py --csv raexpert_debt_ratings.csv
python parser_raexpert_debt.py --timeout 90
```

## Тесты

```bash
python -m unittest discover -s tests -v
```
