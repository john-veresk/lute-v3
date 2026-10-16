# Selkouutiset → Lute

Из корня проекта извлечь выпуск по дате:

```sh
.venv/bin/python -m scripts.extract_selkouutiset --date 2026-10-15
```

Скрипт находит выпуск в текущем списке Yle, проверяет дату в заголовке и сохраняет
финский текст без меню, подписей к изображениям и служебных блоков. Дату нужно
указывать полностью, включая год. Если выпуск уже исчез из текущего списка,
передайте прямую ссылку на статью:

```sh
.venv/bin/python -m scripts.extract_selkouutiset --url https://yle.fi/a/74-20251625 --date 2026-10-15
```

Файлы по умолчанию: `output/text/selkouutiset-2026-10-15-fi.txt` и соседний CSV.
CSV содержит заголовок, текст, язык `Finnish`, тег `selkouutiset` и ссылку на источник.
Можно задать другую папку через `--output-dir`. Существующие файлы скрипт не заменяет.
При недоступной странице, неоднозначной дате или изменившейся разметке он завершится
с ошибкой. Новых зависимостей нет: используются `requests` и `beautifulsoup4` из проекта.

Скрипт сохраняет файлы; импорт в базу выполняется штатной командой Lute.
Сначала проверить импорт без записи:

```sh
.venv/bin/flask --app lute.app_factory cli import_books_from_csv output/text/selkouutiset-2026-10-15-fi.csv
```

После проверки и резервного копирования базы выполнить импорт:

```sh
.venv/bin/flask --app lute.app_factory cli import_books_from_csv --commit output/text/selkouutiset-2026-10-15-fi.csv
```

Язык `Finnish` должен существовать в Lute. Команда импорта пропускает уже
существующую книгу с тем же заголовком и языком.

Проверки скрипта без запуска тестовой базы Lute:

```sh
.venv/bin/python -m pytest --confcutdir=tests/unit/cli tests/unit/cli/test_extract_selkouutiset.py
```
