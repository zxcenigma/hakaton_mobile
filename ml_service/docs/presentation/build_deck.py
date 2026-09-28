"""Build the competition deck for «Монетка».

Kept as a script, not as a hand-made file, for the same reason the dashboards are
version-controlled JSON: a deck that only exists as a binary is one nobody can
diff, review or regenerate after the content changes.

Palette is taken verbatim from the app's `AppPalette` (mobile_app/lib/app/theme/
app_theme.dart), so the deck, the repository banner and the product read as one
thing.

Structure follows ТЗ §4 — all nine required content points across 12 slides:

    1  титул                      7  UX/UI-решения                  (§4.6)
    2  проблема и аудитория (§4.1) 8  архитектура и стек             (§4.7)
    3  образовательные результаты  9  обновление учебного контента   (§4.7)
       (§4.2)                     10  ML: зачем и почему безопасно
    4  идея продукта       (§4.3) 11  результаты тестирования        (§4.8)
    5  путь и экономика    (§4.4) 12  ограничения, план, ссылки (§4.8, §4.9)
    6  функции и границы   (§4.5)

Usage:  python docs/presentation/build_deck.py
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).with_name("monetka-presentation.pptx")

# ---------------------------------------------------------------- palette --
# Straight from AppPalette in the Flutter app.
STAGE = RGBColor(0x21, 0x1E, 0x1C)       # scaffold background
STAGE_LIGHT = RGBColor(0x51, 0x46, 0x3D)
PODIUM = RGBColor(0x71, 0x60, 0x52)
PODIUM_EDGE = RGBColor(0x30, 0x29, 0x23)
GOLD = RGBColor(0xE5, 0xC7, 0x8F)
DARK_GOLD = RGBColor(0x46, 0x3A, 0x28)
CERAMIC = RGBColor(0xF0, 0xDD, 0xC3)
CERAMIC_SHADE = RGBColor(0xC4, 0xAA, 0x8E)
ROSE = RGBColor(0xD7, 0xAA, 0xA0)
CARD = RGBColor(0x2A, 0x25, 0x23)

# Both fonts ship with Office and render true-to-width, so the layout that is
# checked here is the layout the jury sees.
SERIF = "Cambria"
SANS = "Calibri"

W = Inches(13.333)
H = Inches(7.5)
MARGIN = Inches(0.7)


# ----------------------------------------------------------------- helpers --


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    return prs


def blank(prs: Presentation):
    """A slide with the stage background and nothing else."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = STAGE
    bg.line.fill.background()
    bg.shadow.inherit = False
    return slide


def textbox(
    slide,
    left,
    top,
    width,
    height,
    text,
    *,
    size=16,
    color=CERAMIC,
    bold=False,
    font=SANS,
    align=PP_ALIGN.LEFT,
    line_spacing=1.25,
    anchor=MSO_ANCHOR.TOP,
    space_after=0,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0

    lines = text.split("\n")
    for index, line in enumerate(lines):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.alignment = align
        para.line_spacing = line_spacing
        if space_after:
            para.space_after = Pt(space_after)
        run = para.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = font
        run.font.color.rgb = color
    return box


def title(slide, text, *, sub: str | None = None):
    textbox(
        slide,
        MARGIN,
        Inches(0.52),
        W - 2 * MARGIN,
        Inches(0.85),
        text,
        size=34,
        color=GOLD,
        bold=True,
        font=SERIF,
    )
    if sub:
        textbox(
            slide,
            MARGIN,
            Inches(1.33),
            W - 2 * MARGIN,
            Inches(0.4),
            sub,
            size=14,
            color=CERAMIC_SHADE,
        )


def card(slide, left, top, width, height, *, fill=CARD):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = DARK_GOLD
    shape.line.width = Pt(1)
    shape.shadow.inherit = False
    shape.adjustments[0] = 0.06
    return shape


def coin(slide, cx, cy, diameter, label, *, label_size=18):
    """The visual motif: a gold coin. Repeated on every content slide."""
    left = Emu(int(cx - diameter / 2))
    top = Emu(int(cy - diameter / 2))
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, Emu(int(diameter)), Emu(int(diameter)))
    shape.fill.solid()
    shape.fill.fore_color.rgb = GOLD
    shape.line.color.rgb = DARK_GOLD
    shape.line.width = Pt(1.25)
    shape.shadow.inherit = False

    frame = shape.text_frame
    frame.word_wrap = False
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = frame.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    run = para.add_run()
    run.text = label
    run.font.size = Pt(label_size)
    run.font.bold = True
    run.font.name = SERIF
    run.font.color.rgb = STAGE
    return shape


def stat(slide, left, top, width, value, caption, *, value_size=40, color=GOLD):
    textbox(
        slide, left, top, width, Inches(0.72), value,
        size=value_size, color=color, bold=True, font=SERIF, align=PP_ALIGN.CENTER,
        line_spacing=1.0,
    )
    textbox(
        slide, left, top + Inches(0.66), width, Inches(0.7), caption,
        size=11, color=CERAMIC_SHADE, align=PP_ALIGN.CENTER, line_spacing=1.15,
    )


def bullets(slide, left, top, width, items, *, size=14, gap=10, color=CERAMIC):
    """Bulleted lines using a gold dot drawn as text, one paragraph per item."""
    box = slide.shapes.add_textbox(left, top, width, Inches(0.4) * len(items))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    for index, item in enumerate(items):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.line_spacing = 1.25
        para.space_after = Pt(gap)
        dot = para.add_run()
        dot.text = "◆  "
        dot.font.size = Pt(size - 3)
        dot.font.name = SANS
        dot.font.color.rgb = GOLD
        run = para.add_run()
        run.text = item
        run.font.size = Pt(size)
        run.font.name = SANS
        run.font.color.rgb = color
    return box


def footer(slide, number: int, note: str = ""):
    textbox(
        slide, MARGIN, H - Inches(0.62), Inches(9.0), Inches(0.3), note,
        size=10, color=PODIUM,
    )
    textbox(
        slide, W - MARGIN - Inches(0.6), H - Inches(0.62), Inches(0.6), Inches(0.3),
        f"{number:02d}", size=11, color=DARK_GOLD, bold=True, font=SERIF,
        align=PP_ALIGN.RIGHT,
    )


# ------------------------------------------------------------------ slides --


def slide_title(prs):
    slide = blank(prs)

    # Podium the product's cat stands on, echoed from the app's home screen.
    podium = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(3.2), Inches(4.75), Inches(6.93), Inches(0.7)
    )
    podium.fill.solid()
    podium.fill.fore_color.rgb = PODIUM_EDGE
    podium.line.fill.background()
    podium.shadow.inherit = False

    coin(slide, Inches(1.95), Inches(2.9), Inches(1.15), "₽", label_size=30)
    coin(slide, Inches(11.38), Inches(2.9), Inches(1.15), "₽", label_size=30)

    textbox(
        slide, MARGIN, Inches(2.15), W - 2 * MARGIN, Inches(1.2), "МОНЕТКА",
        size=66, color=GOLD, bold=True, font=SERIF, align=PP_ALIGN.CENTER,
        line_spacing=1.0,
    )
    textbox(
        slide, MARGIN, Inches(3.42), W - 2 * MARGIN, Inches(0.5),
        "Мобильное приложение финансовой грамотности для детей 7–11 лет",
        size=17, color=CERAMIC, align=PP_ALIGN.CENTER,
    )
    textbox(
        slide, MARGIN, Inches(3.98), W - 2 * MARGIN, Inches(0.45),
        "Виртуальный котик, который растёт от разумных финансовых решений",
        size=13, color=CERAMIC_SHADE, align=PP_ALIGN.CENTER,
    )
    textbox(
        slide, MARGIN, Inches(5.62), W - 2 * MARGIN, Inches(0.4),
        "Flutter  ·  Android 8.0+  ·  офлайн  ·  без регистрации и персональных данных",
        size=13, color=CERAMIC_SHADE, align=PP_ALIGN.CENTER,
    )
    textbox(
        slide, MARGIN, Inches(6.5), W - 2 * MARGIN, Inches(0.4),
        "Департамент финансов города Москвы  ·  конкурсный прототип",
        size=12, color=PODIUM, align=PP_ALIGN.CENTER,
    )
    return slide


def slide_problem(prs):
    slide = blank(prs)
    title(slide, "Проблема и целевая аудитория", sub="ТЗ §1 — контекст и актуальность")

    col = Inches(5.9)
    textbox(
        slide, MARGIN, Inches(2.05), col, Inches(2.6),
        "Дети получают карманные деньги, денежные подарки и участвуют "
        "в семейных покупках раньше, чем начинают понимать, откуда берутся "
        "деньги и как ими распоряжаться.\n\n"
        "В 7–11 лет ребёнок уже умеет сравнивать цены и копить на понятную "
        "цель — но абстрактные объяснения про доходы и расходы быстро "
        "утомляют.",
        size=15, line_spacing=1.35,
    )

    right = MARGIN + col + Inches(0.6)
    width = W - right - MARGIN
    card(slide, right, Inches(1.95), width, Inches(3.55))
    textbox(
        slide, right + Inches(0.4), Inches(2.25), width - Inches(0.8), Inches(0.4),
        "ЧЕГО НЕ ХВАТАЕТ", size=12, color=GOLD, bold=True,
    )
    bullets(
        slide, right + Inches(0.4), Inches(2.8), width - Inches(0.8),
        [
            "инструмента, где решение принимается самостоятельно",
            "мгновенно видимого последствия этого решения",
            "возможности ошибиться без риска и исправиться",
        ],
        size=14, gap=14,
    )

    textbox(
        slide, MARGIN, Inches(4.55), col, Inches(0.85),
        "Формат виртуального питомца делает это наглядным: от распределения "
        "ресурсов зависит настроение и дальнейшее развитие персонажа.",
        size=14, color=ROSE, line_spacing=1.3,
    )

    # Stats sit above the footer with room to spare: at 6.15 the captions ran
    # past the bottom of the slide and collided with the footer line.
    y = Inches(5.62)
    stat(slide, MARGIN, y, Inches(2.4), "7–11", "возраст основного\nпользователя", value_size=34)
    stat(slide, MARGIN + Inches(2.9), y, Inches(2.4), "0 ₽", "реальных денег\nв приложении", value_size=34)
    stat(slide, MARGIN + Inches(5.8), y, Inches(2.4), "6", "компетенций\nЕдиной рамки", value_size=34)
    footer(slide, 2, "Целевая аудитория: дети, только знакомящиеся с карманными деньгами")
    return slide


def slide_competencies(prs):
    slide = blank(prs)
    title(
        slide,
        "Образовательные результаты",
        sub="Единая рамка компетенций, раздел 6 — базовый уровень, начальное общее образование",
    )

    items = [
        ("1", "Понимать назначение бюджета", "расходы не превышают доходов"),
        ("2", "Различать нужное и желаемое", "обязательные и необязательные расходы"),
        ("3", "Планировать в ограничении", "решения при ограниченном бюджете"),
        ("4", "Ставить цель и копить", "краткосрочная цель, регулярные отчисления"),
        ("5", "Оценивать свои решения", "объяснять, к чему они привели"),
        ("6", "Действовать со взрослым", "приложение + значимый взрослый"),
    ]

    card_w = Inches(3.9)
    card_h = Inches(2.05)
    gap_x = Inches(0.42)
    gap_y = Inches(0.35)
    x0 = MARGIN
    y0 = Inches(2.0)

    for index, (number, head, detail) in enumerate(items):
        row, col = divmod(index, 3)
        left = x0 + col * (card_w + gap_x)
        top = y0 + row * (card_h + gap_y)
        card(slide, left, top, card_w, card_h)
        coin(slide, left + Inches(0.62), top + Inches(0.6), Inches(0.62), number, label_size=16)
        textbox(
            slide, left + Inches(1.1), top + Inches(0.34), card_w - Inches(1.5), Inches(0.9),
            head, size=15, color=GOLD, bold=True, font=SERIF, line_spacing=1.1,
        )
        textbox(
            slide, left + Inches(0.35), top + Inches(1.28), card_w - Inches(0.7), Inches(0.6),
            detail, size=12, color=CERAMIC_SHADE, line_spacing=1.2,
        )

    footer(slide, 3, "Каждая компетенция привязана к заданию и к метрике витрины — content/competencies.yaml")
    return slide


def slide_idea(prs):
    slide = blank(prs)
    title(slide, "Идея продукта", sub="Почему механика питомца формирует финансовый навык")

    textbox(
        slide, MARGIN, Inches(2.0), Inches(5.6), Inches(1.5),
        "Ребёнок принимает решение — и сразу видит, что изменилось.\n"
        "Котик не абстрактный счёт: он реагирует, и реакцию можно объяснить "
        "одной фразой.",
        size=16, line_spacing=1.35,
    )

    textbox(
        slide, MARGIN, Inches(3.6), Inches(5.6), Inches(0.35),
        "ТРИ ТИПА РЕШЕНИЙ — ВЕСЬ ИГРОВОЙ ЦИКЛ", size=12, color=GOLD, bold=True,
    )
    choices = [
        ("Потратить на обязательное", "еда, уход, сон — котик бодрый"),
        ("Потратить на желаемое", "игрушка, украшение — котик рад"),
        ("Отложить", "цель становится ближе"),
    ]
    for index, (head, detail) in enumerate(choices):
        top = Inches(4.1) + index * Inches(0.78)
        coin(slide, MARGIN + Inches(0.22), top + Inches(0.26), Inches(0.44), "◆", label_size=12)
        textbox(
            slide, MARGIN + Inches(0.62), top, Inches(5.0), Inches(0.32),
            head, size=14, color=CERAMIC, bold=True,
        )
        textbox(
            slide, MARGIN + Inches(0.62), top + Inches(0.3), Inches(5.0), Inches(0.3),
            detail, size=12, color=CERAMIC_SHADE,
        )

    right = Inches(7.1)
    width = W - right - MARGIN
    card(slide, right, Inches(1.95), width, Inches(4.55))
    textbox(
        slide, right + Inches(0.45), Inches(2.3), width - Inches(0.9), Inches(0.35),
        "ПРИНЦИПЫ РЕШЕНИЯ", size=12, color=GOLD, bold=True,
    )
    principles = [
        ("Обучение действием", "сначала выбор, потом видимое последствие"),
        ("Объяснимость", "ответ на «что изменилось и почему»"),
        ("Безопасная ошибка", "неудача — учебная задача, а не потеря прогресса"),
        ("Возрастная уместность", "короткие фразы, целые числа, крупные элементы"),
        ("Финансовая нейтральность", "без рекламы продуктов и персональных советов"),
    ]
    for index, (head, detail) in enumerate(principles):
        top = Inches(2.8) + index * Inches(0.72)
        textbox(
            slide, right + Inches(0.45), top, width - Inches(0.9), Inches(0.3),
            head, size=14, color=ROSE, bold=True,
        )
        textbox(
            slide, right + Inches(0.45), top + Inches(0.28), width - Inches(0.9), Inches(0.32),
            detail, size=12, color=CERAMIC_SHADE,
        )

    footer(slide, 4, "ТЗ §2.1–2.2 — цель продукта и принципы решения")
    return slide


def slide_loop(prs):
    slide = blank(prs)
    title(slide, "Пользовательский путь и игровая экономика", sub="ТЗ §2.4, Приложение А — сквозной сценарий")

    steps = [
        ("1", "Профиль", "гостевой режим,\nбез регистрации"),
        ("2", "Котик", "внешний вид\nи имя"),
        ("3", "Доход", "источник и сумма\nвсегда названы"),
        ("4", "План", "три направления,\nбольше бюджета нельзя"),
        ("5", "Задания", "ситуация с выбором\nи объяснением"),
        ("6", "Покупки", "цена, категория,\nвлияние — до покупки"),
        ("7", "Копилка", "цель, срок\nпо средней сумме"),
        ("8", "Итог", "план против факта,\nреакция котика"),
    ]

    # Eight steps have to fit between the margins: 8·1.27 + 7·0.245 = 11.88",
    # leaving 0.76" on the right. At 1.38" the last step ran off the slide.
    x0 = MARGIN
    box_w = Inches(1.27)
    gap = Inches(0.245)
    top = Inches(2.15)

    for index, (number, head, detail) in enumerate(steps):
        left = x0 + index * (box_w + gap)
        coin(slide, left + box_w / 2, top + Inches(0.36), Inches(0.72), number, label_size=17)
        textbox(
            slide, left, top + Inches(0.88), box_w, Inches(0.3), head,
            size=13, color=GOLD, bold=True, align=PP_ALIGN.CENTER, font=SERIF,
        )
        textbox(
            slide, left, top + Inches(1.2), box_w, Inches(0.7), detail,
            size=10, color=CERAMIC_SHADE, align=PP_ALIGN.CENTER, line_spacing=1.2,
        )
        if index < len(steps) - 1:
            textbox(
                slide, left + box_w, top + Inches(0.22), gap, Inches(0.3), "›",
                size=20, color=DARK_GOLD, align=PP_ALIGN.CENTER,
            )

    textbox(
        slide, MARGIN, Inches(4.25), W - 2 * MARGIN, Inches(0.3),
        "Цикл повторяется. Стадия котика меняется по совокупности решений за несколько периодов.",
        size=13, color=ROSE, align=PP_ALIGN.CENTER,
    )

    card(slide, MARGIN, Inches(4.75), W - 2 * MARGIN, Inches(1.9))
    # Full-width so the heading stays on one line; at 5.0" it wrapped and the
    # second line landed on the labels below.
    textbox(
        slide, MARGIN + Inches(0.45), Inches(5.0), W - 2 * MARGIN - Inches(0.9), Inches(0.3),
        "ФОРМУЛЫ ЭКОНОМИКИ — ДЕТЕРМИНИРОВАННЫЕ И ОБЪЯСНИМЫЕ",
        size=12, color=GOLD, bold=True,
    )
    # Plain ASCII-ish notation: ⌈⌉ has no glyph in Cambria and rendered as [ ].
    formulas = [
        ("Соответствие плану", "1 − Σ|факт − план| / план"),
        ("Покрытие обязательного", "факт / потребность периода"),
        ("Срок до цели, с округлением вверх", "(стоимость − накоплено) / средний взнос"),
    ]
    for index, (name, formula) in enumerate(formulas):
        left = MARGIN + Inches(0.45) + index * Inches(3.8)
        textbox(
            slide, left, Inches(5.45), Inches(3.65), Inches(0.28), name,
            size=11, color=CERAMIC_SHADE,
        )
        textbox(
            slide, left, Inches(5.76), Inches(3.65), Inches(0.6), formula,
            size=13, color=CERAMIC, bold=True, font=SERIF, line_spacing=1.15,
        )

    footer(slide, 5, "Ни одна из этих величин не предсказывается моделью — все считаются формулой")
    return slide


def slide_scope(prs):
    slide = blank(prs)
    title(slide, "Обязательные функции и границы прототипа", sub="ТЗ §2.5 — что реализовано, §2.7 — чего намеренно нет")

    half = Inches(6.0)
    card(slide, MARGIN, Inches(1.95), half, Inches(4.55))
    textbox(
        slide, MARGIN + Inches(0.42), Inches(2.25), half - Inches(0.84), Inches(0.32),
        "РЕАЛИЗОВАНО", size=12, color=GOLD, bold=True,
    )
    bullets(
        slide, MARGIN + Inches(0.42), Inches(2.75), half - Inches(0.84),
        [
            "Гостевой режим без регистрации и без персональных данных",
            "План бюджета по трём направлениям с контролем превышения",
            "Каталог из 14 позиций: обязательные и необязательные",
            "9 заданий по трём темам с объяснением любого ответа",
            "5 целей накопления, понятный срок по средней сумме",
            "27 комбинаций котика, 4 стадии развития",
            "Демонстрационный режим и сброс тестового профиля",
            "Раздел взрослого за простым барьером",
        ],
        size=13, gap=9,
    )

    right = MARGIN + half + Inches(0.6)
    width = W - right - MARGIN
    card(slide, right, Inches(1.95), width, Inches(4.55), fill=PODIUM_EDGE)
    textbox(
        slide, right + Inches(0.42), Inches(2.25), width - Inches(0.84), Inches(0.32),
        "ЗА ГРАНИЦАМИ — ОСОЗНАННО", size=12, color=ROSE, bold=True,
    )
    # One rendered line each: the longer wording wrapped to eight lines and the
    # last item ran under the closing sentence below.
    bullets(
        slide, right + Inches(0.42), Inches(2.75), width - Inches(0.84),
        [
            "Реальные счета, карты, СБП, госсистемы",
            "Настоящие деньги, подписки, реклама",
            "Чаты между детьми, публичные рейтинги",
            "Обязательный ИИ — вне минимума ТЗ",
            "Родительский веб-кабинет и удалённый контроль",
        ],
        size=13, gap=14, color=CERAMIC_SHADE,
    )
    textbox(
        slide, right + Inches(0.42), Inches(5.35), width - Inches(0.84), Inches(1.0),
        "Игровая валюта не имеет реальной стоимости, не продаётся "
        "и не обменивается на деньги или призы.",
        size=12, color=ROSE, line_spacing=1.3,
    )

    footer(slide, 6, "Матрица соответствия по каждому пункту — docs/compliance-tz.md")
    return slide


def slide_ux(prs):
    slide = blank(prs)
    title(slide, "Ключевые UX/UI-решения", sub="ТЗ §3.6 — возрастная уместность и доступность")

    sections = [
        ("Цели", "стоимость, накоплено,\nосталось, срок"),
        ("Советник", "что произошло\nи что делать дальше"),
        ("Магазин", "цена, категория\nи влияние до покупки"),
        ("Мяу", "состояние котика\nи причина изменения"),
    ]
    card_w = Inches(2.85)
    gap = Inches(0.36)
    for index, (name, detail) in enumerate(sections):
        left = MARGIN + index * (card_w + gap)
        card(slide, left, Inches(2.0), card_w, Inches(1.75))
        textbox(
            slide, left + Inches(0.3), Inches(2.25), card_w - Inches(0.6), Inches(0.35),
            name, size=18, color=GOLD, bold=True, font=SERIF,
        )
        textbox(
            slide, left + Inches(0.3), Inches(2.7), card_w - Inches(0.6), Inches(0.8),
            detail, size=12, color=CERAMIC_SHADE, line_spacing=1.25,
        )

    textbox(
        slide, MARGIN, Inches(4.1), Inches(6.0), Inches(0.32),
        "ТЁМНО-ЗОЛОТОЙ СЕТТИНГ", size=12, color=GOLD, bold=True,
    )
    textbox(
        slide, MARGIN, Inches(4.5), Inches(6.0), Inches(1.5),
        "Котик на подиуме в тёплом свете: сцена, а не интерфейс банка. "
        "Золото читается как «ценность» без единого упоминания реальных денег — "
        "и отличает приложение от привычной детской пестроты.",
        size=14, line_spacing=1.35,
    )
    textbox(
        slide, MARGIN, Inches(6.0), Inches(6.0), Inches(0.55),
        "Демонстрационный режим: обязательный сценарий проходится подряд, "
        "без ожидания календарных сроков.",
        size=12, color=ROSE, line_spacing=1.3,
    )

    right = Inches(7.1)
    width = W - right - MARGIN
    textbox(
        slide, right, Inches(4.1), width, Inches(0.32),
        "ДОСТУПНОСТЬ", size=12, color=GOLD, bold=True,
    )
    bullets(
        slide, right, Inches(4.5), width,
        [
            "Цель нажатия не меньше 48 × 48 dp",
            "Основной текст от 16 sp, выдерживает системное увеличение",
            "Цвет никогда не единственный носитель смысла",
            "Звук и анимации отключаются",
            "Удаление данных требует подтверждения",
        ],
        size=12, gap=7,
    )

    footer(slide, 7, "Палитра приложения использована и в этой презентации, и в оформлении репозитория")
    return slide


def slide_architecture(prs):
    slide = blank(prs)
    title(slide, "Архитектура, стек и хранение данных", sub="ТЗ §3.2, §3.4 — компоненты и разделение ответственности")

    layers = [
        (
            "Приложение — Flutter",
            "Android 8.0+ · портретная ориентация от 360 dp",
            "Вся игровая экономика, состояние и рост котика. Работает офлайн. "
            "Локальное хранилище на устройстве.",
            GOLD,
        ),
        (
            "Учебный контент — YAML",
            "каталог · задания · цели · правила котика · карта компетенций",
            "Отделён от кода интерфейса. Новое задание добавляется правкой файла, "
            "без пересборки логики.",
            ROSE,
        ),
        (
            "Дата-платформа — Python",
            "bronze → silver → gold (dbt) · FastAPI + OpenAPI · Docker Compose",
            "Синтетическая телеметрия, витрины, обучение и экспорт моделей "
            "на устройство. Не на критическом пути игры.",
            CERAMIC_SHADE,
        ),
    ]

    # Three cards plus the closing line have to clear the footer: at 1.4"/0.26"
    # the third card ran under the sentence below it.
    top = Inches(1.95)
    height = Inches(1.28)
    gap = Inches(0.22)
    for index, (head, stack, detail, color) in enumerate(layers):
        y = top + index * (height + gap)
        card(slide, MARGIN, y, W - 2 * MARGIN, height)
        coin(slide, MARGIN + Inches(0.6), y + height / 2, Inches(0.68), str(index + 1), label_size=17)
        textbox(
            slide, MARGIN + Inches(1.15), y + Inches(0.22), Inches(4.2), Inches(0.35),
            head, size=17, color=color, bold=True, font=SERIF,
        )
        textbox(
            slide, MARGIN + Inches(1.15), y + Inches(0.66), Inches(4.4), Inches(0.5),
            stack, size=11, color=PODIUM,
        )
        textbox(
            slide, MARGIN + Inches(5.8), y + Inches(0.3), W - MARGIN * 2 - Inches(6.3), Inches(0.85),
            detail, size=13, color=CERAMIC, line_spacing=1.3,
        )

    textbox(
        slide, MARGIN, Inches(6.4), W - 2 * MARGIN, Inches(0.38),
        "Приложение полностью работоспособно без платформы: она добавляет аналитику и подсказки, "
        "но не является условием работы игрового цикла.",
        size=13, color=ROSE, align=PP_ALIGN.CENTER,
    )
    footer(slide, 8, "Подробная схема и обоснования — docs/architecture.md")
    return slide


def slide_content_updates(prs):
    slide = blank(prs)
    title(slide, "Обновление учебного контента", sub="ТЗ §2.5.14 — новое задание без переработки логики")

    textbox(
        slide, MARGIN, Inches(2.0), Inches(5.9), Inches(1.3),
        "Контент — это данные, а не код. Методист правит YAML, "
        "приложение и витрины подхватывают изменение без участия разработчика.",
        size=15, line_spacing=1.35,
    )

    steps = [
        ("Правка YAML", "методист добавляет задание в content/quests.yaml"),
        ("Контрактные тесты", "минимумы ТЗ §2.6, возрастная арифметика, тон формулировок"),
        ("Сборка витрин", "seed'ы dbt генерируются из того же файла — рассинхрон невозможен"),
        ("Манифест", "приложение сверяет версию контента и забирает разницу"),
    ]
    for index, (head, detail) in enumerate(steps):
        top = Inches(3.5) + index * Inches(0.82)
        coin(slide, MARGIN + Inches(0.24), top + Inches(0.26), Inches(0.48), str(index + 1), label_size=13)
        textbox(
            slide, MARGIN + Inches(0.68), top, Inches(5.3), Inches(0.3),
            head, size=14, color=GOLD, bold=True,
        )
        textbox(
            slide, MARGIN + Inches(0.68), top + Inches(0.29), Inches(5.3), Inches(0.32),
            detail, size=12, color=CERAMIC_SHADE,
        )

    right = Inches(7.1)
    width = W - right - MARGIN
    card(slide, right, Inches(1.95), width, Inches(4.55))
    textbox(
        slide, right + Inches(0.45), Inches(2.25), width - Inches(0.9), Inches(0.32),
        "ЧТО ПРОВЕРЯЕТСЯ АВТОМАТИЧЕСКИ", size=12, color=GOLD, bold=True,
    )
    # Each item kept to one rendered line: at the previous wording six items
    # wrapped to ten lines and the last one ran under the closing sentence.
    checks = [
        "Минимумы ТЗ §2.6 — по фактическим данным",
        "Арифметика: ответ сверяется вычислением",
        "Объяснение есть у любого варианта ответа",
        "Неудачный выбор тоже приносит награду",
        "Нет стыдящих и пугающих формулировок",
        "Стадии котика не понижаются никогда",
    ]
    bullets(slide, right + Inches(0.45), Inches(2.75), width - Inches(0.9), checks, size=13, gap=12)
    textbox(
        slide, right + Inches(0.45), Inches(5.6), width - Inches(0.9), Inches(0.6),
        "Ошибка в контенте останавливает сборку, а не доходит до ребёнка.",
        size=13, color=ROSE, line_spacing=1.25,
    )

    footer(slide, 9, "content/*.yaml · tests/unit/test_content.py")
    return slide


def slide_ml(prs):
    slide = blank(prs)
    title(
        slide,
        "Машинное обучение: зачем и почему это безопасно",
        sub="ТЗ §2.7.5 не требует ML · §3.2 требует обосновать, если он применяется",
    )

    card(slide, MARGIN, Inches(1.95), W - 2 * MARGIN, Inches(1.15), fill=DARK_GOLD)
    textbox(
        slide, MARGIN + Inches(0.45), Inches(2.18), W - 2 * MARGIN - Inches(0.9), Inches(0.75),
        "Ни одна модель не может изменить баланс, заблокировать покупку, "
        "повлиять на настроение котика или на срок достижения цели.",
        size=17, color=GOLD, bold=True, font=SERIF, align=PP_ALIGN.CENTER,
        line_spacing=1.25,
    )

    columns = [
        (
            "Что модель делает",
            [
                "Выбирает формулировку подсказки в Советнике",
                "Подсказывает порядок заданий — как тай-брейкер",
                "Находит разбалансировку экономики для методиста",
            ],
            GOLD,
        ),
        (
            "Чего не делает никогда",
            [
                "Не трогает баланс и покупки",
                "Не влияет на состояние и стадию котика",
                "Не считает срок до цели — это формула ТЗ §2.5.7",
            ],
            ROSE,
        ),
        (
            "Как это проверено",
            [
                "Состязательные тесты: правила устаивают против вредных оценок",
                "Гейты качества: слабая модель не публикуется",
                "Паритет экспорта: на устройстве проверенная модель",
            ],
            CERAMIC_SHADE,
        ),
    ]
    # 3·3.75 + 2·0.4 = 12.05", so the right column ends 0.58" from the edge.
    # At 3.9"/0.42" the third column's text ran into the slide border.
    col_w = Inches(3.75)
    gap = Inches(0.4)
    for index, (head, items, color) in enumerate(columns):
        left = MARGIN + index * (col_w + gap)
        textbox(
            slide, left, Inches(3.35), col_w, Inches(0.35),
            head, size=15, color=color, bold=True, font=SERIF,
        )
        bullets(slide, left, Inches(3.78), col_w, items, size=12, gap=9)

    # 5.62 rather than 5.5: a wrapped third bullet reached into the card and the
    # last line was clipped by it.
    card(slide, MARGIN, Inches(5.62), W - 2 * MARGIN, Inches(1.0))
    textbox(
        slide, MARGIN + Inches(0.45), Inches(5.82), W - 2 * MARGIN - Inches(0.9), Inches(0.65),
        "Если модель недоступна — показывается подсказка по правилам, и ребёнок не замечает разницы. "
        "Приложение полностью работает без единой модели и при выключенной телеметрии.",
        size=13, color=CERAMIC, align=PP_ALIGN.CENTER, line_spacing=1.3,
    )

    footer(slide, 10, "Карточки моделей с метриками и границами — docs/ml-cards/ · обоснование — docs/adr/0001")
    return slide


def slide_testing(prs):
    slide = blank(prs)
    title(slide, "Результаты проверки", sub="ТЗ §3.4, §4.8 — что проверено автоматически")

    y = Inches(2.05)
    stats = [
        ("300", "автотестов\nпроходят"),
        ("82 %", "покрытие\nкода"),
        ("58", "тестов dbt\nна витринах"),
        ("14", "проверок\nкачества данных"),
    ]
    for index, (value, caption) in enumerate(stats):
        left = MARGIN + index * Inches(3.05)
        card(slide, left, y, Inches(2.75), Inches(1.6))
        stat(slide, left, y + Inches(0.3), Inches(2.75), value, caption, value_size=38)

    textbox(
        slide, MARGIN, Inches(4.0), Inches(5.9), Inches(0.32),
        "ЧТО ИМЕННО ПРОВЕРЯЕТСЯ", size=12, color=GOLD, bold=True,
    )
    bullets(
        slide, MARGIN, Inches(4.45), Inches(5.9),
        [
            "Инварианты экономики: монеты не появляются и не исчезают",
            "Отрицательный баланс непредставим на уровне типа",
            "План не может превысить доступную сумму",
            "Стадия котика не понижается ни при каких данных",
            "Минимумы ТЗ §2.6 подтверждаются по фактическим данным",
        ],
        size=13, gap=9,
    )

    right = Inches(7.1)
    width = W - right - MARGIN
    card(slide, right, Inches(3.9), width, Inches(2.6))
    textbox(
        slide, right + Inches(0.42), Inches(4.15), width - Inches(0.84), Inches(0.32),
        "ПРОВЕРКИ КАЧЕСТВА УМЕЮТ ПАДАТЬ", size=12, color=ROSE, bold=True,
    )
    textbox(
        slide, right + Inches(0.42), Inches(4.6), width - Inches(0.84), Inches(1.7),
        "Каждый инвариант дополнительно проверяется на намеренно испорченных "
        "данных: в таблицу вносится нарушение, и тест требует, чтобы проверка "
        "его поймала.\n\n"
        "Проверка, которая не умеет падать, не доказывает ничего.",
        size=13, color=CERAMIC, line_spacing=1.3,
    )

    footer(slide, 11, "Проверка на физическом Android-устройстве — в отчёте команды по сборке")
    return slide


def slide_links(prs):
    slide = blank(prs)
    title(slide, "Ограничения, план и материалы", sub="ТЗ §4.8, §4.9 — честные границы и ссылки")

    textbox(
        slide, MARGIN, Inches(2.0), Inches(6.0), Inches(0.32),
        "ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ", size=12, color=ROSE, bold=True,
    )
    bullets(
        slide, MARGIN, Inches(2.45), Inches(6.0),
        [
            "Данные платформы синтетические: наблюдать детей без согласия "
            "законных представителей нельзя",
            "Метрики моделей характеризуют корректность конвейера, "
            "а не педагогическую эффективность",
            "Детектор аномалий экономики обучен на малом числе периодов",
            "Полный контейнерный стек описан, но проверялся не на всех средах",
        ],
        size=13, gap=11,
    )

    textbox(
        slide, MARGIN, Inches(4.85), Inches(6.0), Inches(0.32),
        "ПЛАН ДОРАБОТКИ", size=12, color=GOLD, bold=True,
    )
    bullets(
        slide, MARGIN, Inches(5.3), Inches(6.0),
        [
            "Проверка на физических устройствах и подписанная релизная сборка",
            "Интеграционные тесты потоковой части",
            "Исследование с согласием представителей — до любых заявлений об эффекте",
        ],
        size=13, gap=9,
    )

    right = Inches(7.3)
    width = W - right - MARGIN
    card(slide, right, Inches(1.95), width, Inches(4.55))
    textbox(
        slide, right + Inches(0.45), Inches(2.25), width - Inches(0.9), Inches(0.32),
        "МАТЕРИАЛЫ", size=12, color=GOLD, bold=True,
    )

    links = [
        ("Репозиторий", "github.com/zxcenigma/hakaton_mobile"),
        ("Приложение", "ветка frontend · mobile_app/"),
        ("Дата-платформа", "ветка ml-platform · monetka-data-platform/"),
        ("Документация", "docs/ — архитектура, ADR, карточки моделей"),
        ("Матрица ТЗ", "docs/compliance-tz.md"),
        ("Запуск за 2 минуты", "monetka demo"),
    ]
    for index, (name, value) in enumerate(links):
        top = Inches(2.8) + index * Inches(0.62)
        textbox(
            slide, right + Inches(0.45), top, width - Inches(0.9), Inches(0.26),
            name, size=11, color=CERAMIC_SHADE,
        )
        textbox(
            slide, right + Inches(0.45), top + Inches(0.24), width - Inches(0.9), Inches(0.3),
            value, size=13, color=CERAMIC, bold=True,
        )

    footer(slide, 12, "Сборка APK, демонстрационный режим и сброс профиля — в инструкции репозитория")
    return slide


# -------------------------------------------------------------------- main --

BUILDERS = (
    slide_title,
    slide_problem,
    slide_competencies,
    slide_idea,
    slide_loop,
    slide_scope,
    slide_ux,
    slide_architecture,
    slide_content_updates,
    slide_ml,
    slide_testing,
    slide_links,
)

NOTES = {
    1: "Приветствие. Приложение учит детей 7-11 лет управлять карманными деньгами через заботу о котике.",
    2: "Проблема: дети распоряжаются деньгами раньше, чем понимают их. Нужен безопасный тренажёр.",
    3: "Привязка к Единой рамке компетенций. Каждая компетенция измеряется метрикой витрины.",
    4: "Три типа решений — это весь игровой цикл. Принципы задают тон продукта.",
    5: "Сквозной сценарий Приложения А. Подчеркнуть: все величины считаются формулой, не моделью.",
    6: "Что сделано и чего намеренно нет. Границы — это решение, а не недоработка.",
    7: "Тёмно-золотой сеттинг отличает продукт. Доступность по рекомендациям Android.",
    8: "Три слоя. Главное: приложение работает без платформы.",
    9: "Контент как данные. Ошибка в контенте останавливает сборку.",
    10: "Ключевой слайд защиты: ML не обязателен по ТЗ, поэтому его роль строго ограничена и проверена.",
    11: "Цифры проверки. Отдельно: проверки качества умеют падать — это доказано тестами.",
    12: "Честные ограничения повышают доверие. Ссылки на репозиторий и документацию.",
}


def build() -> Path:
    prs = new_deck()
    for index, builder in enumerate(BUILDERS, start=1):
        slide = builder(prs)
        note = NOTES.get(index)
        if note:
            slide.notes_slide.notes_text_frame.text = note
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"written: {path}  ({path.stat().st_size / 1024:.0f} KB)")
