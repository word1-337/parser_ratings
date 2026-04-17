# RAExpert parsers

В репозитории две отдельные утилиты:

1. `parser_raexpert_debt.py` — парсер страницы `https://raexpert.ru/ratings/debt_inst/`.
2. `company_finder/company_finder.py` — поиск страницы эмитента в базе RAEX по «кривому» названию компании.

## 1) Парсер рейтингов долговых инструментов

Извлекает:

- кредитный рейтинг;
- дату рейтингового действия;
- название выпуска (эмиссии).

### Запуск

```bash
python parser_raexpert_debt.py
```

По умолчанию результат сохраняется в `raexpert_debt_ratings.json`.

Полезные опции:

```bash
python parser_raexpert_debt.py --max-pages 3
python parser_raexpert_debt.py --csv raexpert_debt_ratings.csv
python parser_raexpert_debt.py --timeout 90
```

## 2) Company finder

Новая папка: `company_finder/`.

Скрипт принимает любое похожее название компании (например, `самолет`, `гк самолет`, `ао самолет`) и пытается вернуть ссылку в формате:

`https://raexpert.ru/database/companies/XXXXXXXXX/`

### Запуск

```bash
python company_finder/company_finder.py "гк самолет"
```

Опции:

```bash
python company_finder/company_finder.py "ао самолет" --min-score 0.5 --timeout 40
```

## Тесты

```bash
python -m unittest discover -s tests -v
```
