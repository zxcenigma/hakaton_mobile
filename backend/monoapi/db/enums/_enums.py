from enum import StrEnum


class OperationType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    INVESTMENT = "investment"


class OperationCategory(StrEnum):
    """Категории товаров и услуг с русскими значениями для API и БД."""

    SUPERMARKETS = "Супермаркеты"
    FAST_FOOD = "Фастфуд"
    RESTAURANTS = "Рестораны"
    COFFEE_SHOPS = "Кофейни"
    FOOD_DELIVERY = "Доставка еды"
    PUBLIC_TRANSPORT = "Общественный транспорт"
    HEALTH = "Здоровье и медицина"
    PHARMACIES = "Аптеки"
    BEAUTY = "Красота и уход"
    SPORTS = "Спорт и фитнес"
    ENTERTAINMENT = "Развлечения"
    CINEMA = "Кино"
    BOOKS = "Книги"
    EDUCATION = "Образование"
    CLOTHING = "Одежда и обувь"
    ACCESSORIES = "Аксессуары и украшения"
    ELECTRONICS = "Электроника и бытовая техника"
    HOME = "Товары для дома"
    CHILDREN = "Детские товары"
    PETS = "Зоотовары"
    FLOWERS = "Цветы"
    GIFTS = "Подарки и сувениры"
    SUBSCRIPTIONS = "Подписки и цифровые сервисы"
    CHARITY = "Благотворительность"
    OTHER = "Прочее"
