"""The icons a category can have: a fixed set, in the groups the app's picker shows them in.

The drawings are the app's (frontend/src/components/category-icons.json, copied from Lucide); this is the list the
server checks names against. tests/guards/test_category_icon_set.py holds the two equal. The system marks lead rows that
are not one category (a transfer, several categories…) and are never a category's own."""

GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Food and home",
        (
            "shopping-cart",
            "utensils",
            "coffee",
            "pizza",
            "cooking-pot",
            "house",
            "sofa",
            "refrigerator",
            "zap",
            "droplets",
            "flame",
            "wifi",
            "wrench",
            "package",
        ),
    ),
    ("Getting around", ("car", "fuel", "bus", "train-front", "bike", "plane", "hotel")),
    (
        "Health and family",
        ("heart-pulse", "pill", "stethoscope", "dumbbell", "baby", "paw-print", "scissors", "graduation-cap", "puzzle"),
    ),
    (
        "Fun and shopping",
        (
            "clapperboard",
            "ticket",
            "tv",
            "music",
            "book-open",
            "shirt",
            "footprints",
            "smartphone",
            "laptop",
            "gift",
            "calendar-clock",
        ),
    ),
    (
        "Money",
        (
            "receipt",
            "landmark",
            "scale",
            "shield-check",
            "trending-up",
            "piggy-bank",
            "hand-coins",
            "hand-heart",
            "heart-handshake",
            "wallet",
            "briefcase",
            "percent",
            "badge-percent",
            "chart-pie",
            "undo-2",
            "circle-ellipsis",
            "tag",
        ),
    ),
)
CHOOSABLE: frozenset[str] = frozenset(name for _, names in GROUPS for name in names)

# What a category has when nobody chose one (existing categories, older files).
DEFAULT = "tag"
# The system marks.
UNCATEGORISED = "circle-dashed"  # the built-in Uncategorised, and a line with no category
SEVERAL = "layers"  # an entry spread over several categories
TRANSFER = "arrow-left-right"  # money between accounts when none has a type
PERSON = "user"  # a loan, a borrowing, a settlement with a person
OPENING = "flag"  # an opening balance or an adjustment
# The account types' own (services/account_types.TYPE_ICONS); the other two types' icons are in the Money group.
CASH = "banknote"
CARD = "credit-card"
SYSTEM: frozenset[str] = frozenset({UNCATEGORISED, SEVERAL, TRANSFER, PERSON, OPENING, CASH, CARD})


def check_icon(name: str) -> str:
    """The name, when a category may have it."""
    if name not in CHOOSABLE:
        raise ValueError(f"'{name}' is not one of finode's category icons")
    return name
