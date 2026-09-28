"""Fill the organiser's ЛЦТ2026 template instead of designing our own deck.

The competition ships `ЛЦТ2026 Шаблон презентации.pptx`: 37 slides, of which
1–6 are instructions to the participants, 7–11 are the mandatory content, and
12–37 are spare layouts and an icon library. The organisers' answers in the
chat were explicit — drop 1–6, keep 7–11, fit the text into the template rather
than restyling it, and «название команды» means the team name alone.

So this script edits the template in place rather than building slides from
nothing: every font, colour and box position stays exactly as the organisers
set it, and only the text changes. Slides beyond the mandatory five are kept
only where we actually use one of the provided layouts.

What this script will NOT write is anything about the people on the team.
Names, phone numbers, messenger handles, places of work and the team's own
history are theirs to supply, and inventing them would put false statements in
a competition submission. Those boxes are filled with a visible marker instead,
and `python build_official_deck.py --todo` lists every one of them.

    python docs/presentation/build_official_deck.py
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt

# Windows consoles here are cp1251 and cannot print «ЛЦТ2026» or a box-drawing
# character; the script would die on its own progress output.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError, OSError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ML_SERVICE_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
# The template lives beside the repository, not inside it: it is the
# organisers' file and is not ours to redistribute.
DEFAULT_TEMPLATE = REPO_ROOT.parent / "ЛЦТ2026 Шаблон презентации.pptx"
DEFAULT_OUTPUT = HERE / "monetka-lct2026.pptx"

#: Written into every field only the team can answer. Deliberately loud: a
#: marker that blends in is a marker that ships.
TODO = "‹ЗАПОЛНИТЬ›"

#: The five slides the organisers require. This is the default output: a
#: submission that contains exactly what was asked for cannot be marked down
#: for containing something else.
MANDATORY = [
    7,  # титул — название команды
    8,  # о команде + описание решения + уникальность
    9,  # участники
    10,  # история команды, выбор задачи, сложности
    11,  # коротко о решении
]

#: Added by `--extended`. Every one of these is a layout the template itself
#: provides — «Проблема и решение», «Стадии», «Статистика», «Пункты» — filled
#: with our content. Nothing is redrawn: the fonts, colours and box positions
#: are the organisers'. Use them only if the rules allow slides beyond 7–11.
OPTIONAL = [
    24,  # «Проблема и решение»
    25,  # «Стадии» — путь данных
    21,  # «Статистика» — измеренные показатели
    15,  # «Пункты» — как закрыт ТЗ
    20,  # «Пункты» — что дальше
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def delete_slides(prs: Presentation, keep: list[int]) -> None:
    """Keep `keep` (1-based template numbers) in that order, drop everything else.

    python-pptx has no API for this. The slide id list and the relationships
    have to be edited directly, and the relationship must be dropped as well as
    the entry — otherwise PowerPoint opens the file and reports it as damaged.
    """
    id_list = prs.slides._sldIdLst
    entries = list(id_list)

    wanted = [entries[n - 1] for n in keep]
    for entry in entries:
        if entry not in wanted:
            prs.part.drop_rel(entry.rId)
        id_list.remove(entry)
    for entry in wanted:
        id_list.append(entry)


def find(slide, name: str):
    """A shape by its name, or None. Names come from the template and are stable."""
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    return None


def shapes_named(slide, name: str) -> list:
    return [s for s in slide.shapes if s.name == name]


def title_of(slide):
    """The slide's title box, whatever the template happened to call it.

    Layouts in this template name it `Заголовок 13`, `Заголовок 5`, `Заголовок 6`
    — looking for one exact name silently left the title unset on half the
    slides, which is only visible by opening the file.
    """
    for shape in slide.shapes:
        if shape.name.startswith("Заголовок"):
            return shape
    return None


def content_boxes(slide, prefix: str = "Текст") -> list:
    """Placeholder text boxes, in template order."""
    return [s for s in slide.shapes if s.is_placeholder and s.name.startswith(prefix)]


def assign(boxes: list, values: list, *, size_pt: float | None = None) -> None:
    """Write `values` into `boxes`, refusing to drop any.

    `zip()` stops at the shorter side without a word. Three bullet points and a
    sixth specification clause disappeared that way, and the deck looked
    complete. A layout that cannot hold the content is a content problem, and
    it should stop the build.
    """
    if len(values) > len(boxes):
        raise ValueError(
            f"{len(values)} значений не помещаются в {len(boxes)} боксов макета — "
            f"лишние: {values[len(boxes):]}"
        )
    for shape, value in zip(boxes, values):
        set_text(shape, value, size_pt=size_pt)


def renumber(prs: Presentation) -> None:
    """Rewrite the page numbers.

    The template's number boxes hold a literal string, not a field, so after
    dropping slides they still read 8, 9, 10, 11, 24, 25… Some are placeholders
    PowerPoint would refresh and some are plain text boxes it would not, so all
    of them are set here.
    """
    for index, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.name.startswith("Номер слайда") and shape.has_text_frame:
                set_text(shape, str(index))


def set_text(shape, lines: list[str] | str, *, size_pt: float | None = None) -> None:
    """Replace a shape's text, keeping the template's formatting.

    Assigning to `text_frame.text` throws away the run properties the template
    carries — font, colour, spacing — and the slide stops matching the others.
    So the first run of the first paragraph is reused as a style carrier and
    every other paragraph is cloned from it.
    """
    if isinstance(lines, str):
        lines = [lines]
    frame = shape.text_frame
    if not frame.paragraphs or not frame.paragraphs[0].runs:
        frame.text = "\n".join(lines)
        if size_pt is not None:
            for paragraph in frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(size_pt)
        return

    template_p = frame.paragraphs[0]
    template_run = template_p.runs[0]

    # Drop every paragraph but the first, then rebuild from the template one.
    for paragraph in list(frame.paragraphs)[1:]:
        paragraph._p.getparent().remove(paragraph._p)
    for run in list(template_p.runs)[1:]:
        run._r.getparent().remove(run._r)

    template_run.text = lines[0]
    if size_pt is not None:
        template_run.font.size = Pt(size_pt)

    for line in lines[1:]:
        new_p = copy.deepcopy(template_p._p)
        template_p._p.getparent().append(new_p)
        frame.paragraphs[-1].runs[0].text = line
        if size_pt is not None:
            frame.paragraphs[-1].runs[0].font.size = Pt(size_pt)


# --------------------------------------------------------------------------
# content
# --------------------------------------------------------------------------


def fill_title(slide) -> None:
    """Slide 7 — the cover. Organisers: this is the team name, nothing else."""
    title = find(slide, "Заголовок 2")
    if title is not None:
        set_text(title, TODO + " название команды")
    subtitle = find(slide, "Текст 4")
    if subtitle is not None:
        set_text(subtitle, "«Монетка» — Департамент финансов города Москвы")


def fill_about_team(slide) -> None:
    """Slide 8 — about the team, what the solution does, what is unique."""
    # The template leaves these title boxes empty; an untitled slide in a
    # submission reads as unfinished.
    set_text(title_of(slide), "О ПРОЕКТЕ")
    boxes = shapes_named(slide, "Текст 8")

    for shape in boxes:
        text = shape.text_frame.text

        if text.startswith("Капитан"):
            set_text(
                shape,
                [
                    f"Капитан: {TODO} ФИО, специальность",
                    f"Кол-во участников: {TODO} человек",
                    f"Краткое описание: {TODO} как образовалась команда,",
                    f"место работы/учёбы участников",
                    f"Город и регион: {TODO}",
                ],
            )

        elif text.startswith("В чем суть"):
            set_text(
                shape,
                [
                    "Мобильное приложение для детей 7–11 лет: ребёнок получает доход, "
                    "распределяет его между обязательным, желаемым и накоплениями, "
                    "покупает в каталоге и копит на цель. Состояние виртуального "
                    "котика отражает качество решений и делает последствия наглядными. "
                    "Взрослый видит прогресс в отдельном разделе. Основной цикл "
                    "работает офлайн, без сервера."
                ],
            )

        elif text.startswith("Что делает ваше решение"):
            set_text(
                shape,
                [
                    "Каждое решение ребёнка объясняется словами, а не баллами: "
                    "приложение всегда называет причину. Объяснение выбирает модель, "
                    "но если она недоступна или отвечает дольше 50 мс — показывается "
                    "правило, поэтому приложение полноценно работает без сети и без ML. "
                    "Экономику игры модели не трогают вообще: цены и доход одинаковы "
                    "для всех. Персональные данные детей не собираются — это проверяет "
                    "код, а не обещает документация."
                ],
            )


def fill_members(slide) -> None:
    """Slide 9 — five member cards. Nothing here can be filled for the team."""
    set_text(title_of(slide), "КОМАНДА")
    for shape in shapes_named(slide, "Текст 8"):
        text = shape.text_frame.text
        if text.startswith("Имя Фамилия"):
            set_text(shape, f"{TODO} Имя Фамилия")
        elif text.startswith("Роль в команде"):
            set_text(
                shape,
                [
                    f"{TODO} роль в команде",
                    f"{TODO} ник в мессенджере",
                    f"{TODO} номер телефона",
                    f"{TODO} место работы/учёбы",
                ],
            )


def fill_team_story(slide) -> None:
    """Slide 10 — history, why this task, what was hard.

    Blocks 01 and 02 are the team's own story and are only sketched. Block 03
    is written out, because the hard parts of this build are documented and
    specific, and a concrete answer there is worth more than a generic one.
    """
    set_text(title_of(slide), "КАК МЫ РАБОТАЛИ")
    for shape in shapes_named(slide, "Текст 8"):
        text = shape.text_frame.text

        if text.startswith("Расскажите, как вы собрались"):
            set_text(
                shape,
                [
                    f"{TODO} как собрались, участвовали ли вместе раньше, "
                    "интересные факты о команде."
                ],
            )

        elif text.startswith("Что вас вдохновило"):
            set_text(
                shape,
                [
                    "Финансовую грамотность детям обычно объясняют текстом и тестами. "
                    "Здесь можно показать последствия решения сразу и мягко: котик "
                    "остался голодным, потому что обязательное не закрыто. Это та "
                    "задача, где интерфейс учит лучше, чем объяснение.",
                ],
            )

        elif text.startswith("Расскажите о самых интересных"):
            set_text(
                shape,
                [
                    "Главная трудность была не технической, а методической: доказать, "
                    "что ML здесь уместен. ТЗ его не требует, поэтому мы ограничили "
                    "модели тем, что можно обосновать, и запретили им трогать игровую "
                    "экономику отдельным решением в репозитории.",
                    "Техническая часть проверялась запуском, а не тестами: 285 тестов "
                    "проходили, а в контейнере сервис падал — путь к данным вычислялся "
                    "от исходников, которых в образе нет. Так нашлись четыре ошибки, "
                    "которые не видны из чекаута.",
                ],
            )


def fill_solution_summary(slide) -> None:
    """Slide 11 — technical essence and marketing essence, side by side."""
    tech = find(slide, "Текст 2")
    if tech is not None:
        set_text(
            tech,
            [
                "Приложение на Flutter, игровой цикл целиком на устройстве: "
                "локальная база, никакой зависимости от сети.",
                "",
                "Рядом — сервис данных и ML. События приложения проходят по слоям "
                "bronze → silver → gold (dbt), обучение идёт с гейтами качества: "
                "модель не выкладывается, если не прошла порог. Модели "
                "конвертируются в ONNX и проверяются на совпадение ответов с "
                "исходной версией, после чего работают прямо на устройстве.",
                "",
                "Стек: Python, DuckDB, dbt, Iceberg, Trino, Redpanda, MLflow, "
                "FastAPI, ONNX Runtime, Docker Compose.",
                "",
                "Персональные данные детей не собираются: контракты событий "
                "отвергают такие поля, и сборка падает.",
            ],
            size_pt=11,
        )

    market = find(slide, "Текст 6")
    if market is not None:
        set_text(
            market,
            [
                "Ближайшее — пилот в московских школах и библиотеках: приложение "
                "работает офлайн, поэтому не требует ни сети в классе, ни "
                "регистрации ребёнка.",
                "",
                "Содержание каталога, заданий и целей меняется без пересборки "
                "приложения, поэтому методист может обновлять материал сам — в том "
                "числе под тематические недели финансовой грамотности.",
                "",
                "Дальше — раздел для взрослого как отдельная ценность: родитель "
                "видит не оценку ребёнка, а разговорные поводы. На этом строится "
                "подписка, не ограничивая базовую бесплатную часть.",
                "",
                "Платформа данных переносится на другие просветительские продукты "
                "департамента: меняется источник событий, конвейер остаётся.",
            ],
            size_pt=11,
        )


def fill_problem_solution(slide) -> None:
    """Template layout «Проблема и решение» — three boxes."""
    set_text(title_of(slide), "ПРОБЛЕМА И РЕШЕНИЕ")
    assign(
        content_boxes(slide),
        [
            "Ребёнок 7–11 лет не связывает решение с последствием: деньги "
            "потрачены, а почему стало хуже — непонятно. Материалы по финансовой "
            "грамотности объясняют правила, но не дают их прожить.",
            "Игровой цикл, где последствие видно сразу и объясняется словами. "
            "Котик реагирует на качество плана, а не на сумму: «обязательное не "
            "закрыто», а не «−10 очков».",
            "Объяснение выбирает модель, обученная на поведении, но приложение от "
            "неё не зависит: нет модели или ответ дольше 50 мс — работает правило. "
            "Экономику игры ML не меняет.",
        ],
        size_pt=12,
    )


def fill_stages(slide) -> None:
    """Template layout «Стадии» — five numbered steps, name and detail each."""
    set_text(title_of(slide), "ПУТЬ ДАННЫХ: ОТ ДЕЙСТВИЯ РЕБЁНКА ДО ПОДСКАЗКИ")
    stages = [
        ("Событие", "Действие в приложении. Ни одного поля о человеке"),
        ("Bronze", "Только добавление, дедупликация по event_id"),
        ("Silver", "Типизированные факты, починка порядка событий"),
        ("Gold", "7 витрин на dbt, 58 проверок качества"),
        ("Модель", "Гейт качества, ONNX, проверка совпадения ответов"),
    ]
    flat: list[str] = []
    for name, detail in stages:
        flat += [name, detail]
    assign(content_boxes(slide), flat)


def fill_statistics(slide, numbers: dict[str, str]) -> None:
    """Template layout «Статистика» — three figures and a chart.

    The chart arrives with invented 2021–2024 data. Left alone it would be the
    only fabricated thing in the deck, on the one slide whose whole point is
    that the numbers are measured.
    """
    set_text(title_of(slide), "ЧТО ИЗМЕРЕНО")
    assign(
        content_boxes(slide),
        [
            numbers["tests"],
            "автотестов проходят",
            numbers["dbt_tests"],
            "проверок dbt на витринах",
            numbers["latency"],
            "медиана ответа модели на устройстве",
        ],
    )
    _replace_chart(slide, numbers)


def _replace_chart(slide, numbers: dict[str, str]) -> None:
    from pptx.chart.data import CategoryChartData

    for shape in slide.shapes:
        if not shape.has_chart:
            continue
        data = CategoryChartData()
        data.categories = ["Модель", "Базовый выбор", "Порог гейта"]
        data.add_series(
            "Точность выбора объяснения",
            (float(numbers["accuracy"]), float(numbers["baseline"]), float(numbers["gate"])),
        )
        shape.chart.replace_data(data)


def fill_tz_points(slide) -> None:
    """Template layout «Пункты» — five clauses, one per box."""
    set_text(title_of(slide), "КАК ЗАКРЫТО ТЗ")
    assign(
        content_boxes(slide),
        [
            "§3.1.5 — основной цикл работает офлайн, на устройстве, без сервера",
            "§3.2 — у каждой модели названы задача, данные и контроль корректности",
            "§3.5 — персональные данные детей не собираются, это проверяет код",
            "§2.5.7 — срок достижения цели считается объяснимой формулой",
            "§3.4 — в репозитории нет паролей, токенов и ключей, проверяет CI",
        ],
        size_pt=13,
    )


def fill_next_steps(slide) -> None:
    """Template layout «Пункты» — six items."""
    set_text(title_of(slide), "ЧТО ДАЛЬШЕ")
    assign(
        content_boxes(slide),
        [
            "Пилот в школах и библиотеках: офлайн, без регистрации ребёнка",
            "Раздел взрослого — разговорные поводы, а не оценка ребёнка",
            "Обновление заданий и каталога без пересборки приложения",
            "Проверка эффекта на когортах: сравнение объяснений по группам",
            "Перенос платформы данных на другие продукты департамента",
            "§5.12 — перечень сторонних библиотек и лицензий поддерживается в репозитории",
        ],
        size_pt=13,
    )


# --------------------------------------------------------------------------


def build(
    template: Path, output: Path, numbers: dict[str, str], *, extended: bool = False
) -> Presentation:
    prs = Presentation(str(template))
    keep = MANDATORY + (OPTIONAL if extended else [])
    delete_slides(prs, keep)

    slides = list(prs.slides)
    fill_title(slides[0])
    fill_about_team(slides[1])
    fill_members(slides[2])
    fill_team_story(slides[3])
    fill_solution_summary(slides[4])
    if extended:
        fill_problem_solution(slides[5])
        fill_stages(slides[6])
        fill_statistics(slides[7], numbers)
        fill_tz_points(slides[8])
        fill_next_steps(slides[9])

    renumber(prs)

    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output))
    return prs


def list_todos(path: Path) -> list[str]:
    """Every box the team still has to fill, by slide."""
    prs = Presentation(str(path))
    found: list[str] = []
    for index, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame and TODO in shape.text_frame.text:
                for line in shape.text_frame.text.splitlines():
                    if TODO in line:
                        found.append(f"слайд {index}: {line.strip()}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--todo", action="store_true", help="only list what is unfilled")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="добавить 5 слайдов на макетах шаблона (только если правила это допускают)",
    )
    parser.add_argument("--tests", default="300")
    parser.add_argument("--dbt-tests", default="58")
    parser.add_argument("--accuracy", default="0.8415")
    parser.add_argument("--baseline", default="0.3333")
    parser.add_argument("--gate", default="0.80")
    parser.add_argument("--latency", default="0.35 мс")
    args = parser.parse_args()

    if args.todo:
        for line in list_todos(args.output):
            print(line)
        return 0

    if not args.template.exists():
        print(f"Шаблон не найден: {args.template}", file=sys.stderr)
        return 1

    build(
        args.template,
        args.output,
        extended=args.extended,
        numbers={
            "tests": args.tests,
            "dbt_tests": args.dbt_tests,
            "accuracy": args.accuracy,
            "baseline": args.baseline,
            "gate": args.gate,
            "latency": args.latency,
        },
    )
    print(f"Готово: {args.output}")
    todos = list_todos(args.output)
    print(f"Осталось заполнить команде: {len(todos)} мест")
    for line in todos:
        print("  ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
