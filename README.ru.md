[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

Интеллектуальный органайзер медицинских записей — автоматическая классификация, извлечение и структурирование разрозненных медицинских документов (фотографии, PDF, Word, текст) в стандартизированные HTML/Markdown/DOCX/XLSX отчёты.

**Основной конвейер**: Исходные файлы → OCR (MinerU batch/single + DeepSeek-OCR) → Обезличивание → LLM-извлечение → Агрегация → Генерация отчётов

Особая благодарность сообществу ❤️ 小胰宝 (Xiaoyibao) и всем open-source контрибьюторам.

---

## Быстрый старт

### 1. Установка зависимостей

```bash
# pyproject.toml (рекомендуется)
uv sync

# или pip
pip install -r requirements.txt
```

### 2. Настройка API ключей

```bash
cp .env.example .env
```

Обязательные ключи:

| Сервис | Назначение | Переменная |
|--------|-----------|-----------|
| **MinerU** | OCR изображений/PDF (основной) | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | LLM-извлечение + DeepSeek-OCR | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLM-резерв | `STEP_API_KEY` |

Опционально:

- `OPENAI_API_KEY` — альтернативный LLM (openai)
- `STEP_API_KEY` — ASR транскрипция

### 3. Запуск тестов

```bash
pytest tests/ -v
```

---

## Использование

### CLI

```bash
./xyb process /path/to/records/ --patient P001 --format all --open
```

Параметры:

| Флаг | Описание |
|------|---------|
| `--patient` | ID пациента (по умолч. P_report_mess) |
| `--format` | Формат вывода: `html` / `md` / `docx` / `xlsx` / `all` |
| `--open` | Автооткрытие HTML |
| `--skip-ocr` | Пропустить OCR (только .md) |
| `--model` | LLM модель, напр. `stepfun:step-3.5-flash` |
| `--force` | Игнорировать предупреждения |

### Запуск конвейера напрямую

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

### OCR одного файла

```bash
python3 scripts/ocr_single.py report.jpg -o result.md
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## Выводы

| Файл | Формат | Описание |
|------|--------|---------|
| `report.html` | HTML | Интерактивный отчёт |
| `case_report.md` | Markdown | Текстовый отчёт |
| `report.docx` | Word | Документ Office |
| `report.xlsx` | Excel | Таблица (анализы/генетика/снимки) |
| `profile.json` | JSON | Данные пациента |
| `mdt_analysis.json` | JSON | MDT анализ |
| `mappings.json` | JSON | Карта обезличивания |

---

## Структура отчёта

```
Стр. 1: Обложка + Обзор (1 минута)
Стр. 2: Хронология лечения
Стр. 3: Тенденции анализов
Стр. 4: Патология и генетика
Стр. 5: Схема лечения
Стр. 6: Инструментальная диагностика
Стр. 7: Ключевые проблемы
Стр. 8: Вопросы для консультации
Стр. 9: Приложения
```

---

## Структура проекта

(идентична английской версии — см. README.en.md)

---

## Возможности

- **Нулевой порог входа** — укажите папку и запустите
- **Мультиформатный ввод** — фото, скан-копии, PDF, Word, текст
- **Умная OCR-маршрутизация** — мало файлов → single MinerU (3 попытки); большой PDF (>10 стр.) или много файлов (>50) → batch MinerU (≤50/пакет, параллельная загрузка); цепочка отката: DeepSeek-OCR → PyMuPDF
- **LLM с контекстом 1M** — полный текст без усечения; max_tokens=256K
- **Двухуровневая классификация** — правила (бесплатно) + LLM-резерв
- **Автообезличивание** — Имя→`[NAME_N]`, Телефон→`[PHONE_N]` с обратимой картой
- **Инкрементальный кеш** — SHA256 дедупликация; автокеш OCR+LLM
- **Мультиформатный вывод** — HTML + Markdown + DOCX + XLSX

---

## Безопасность и конфиденциальность

- ❌ Не ставим диагнозы, не даём рекомендаций
- ✅ Только "систематизация и структурирование"
- **Автообезличивание** с обратимой картой
- **Отказ от ответственности** прилагается ко всем выводам

---

## License

MIT
