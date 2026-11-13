"""Small labelled corpus + questions for retrieval evaluation.

Each question names the document that contains the answer. Extend this file (or add datasets
built from real, de-identified documents) to track retrieval quality as the pipeline changes."""

CORPUS: dict[str, str] = {
    "annual-report": (
        "# Annual Report\n\nQuarterly revenue grew twelve percent in Europe, driven by strong demand for the "
        "new product line. Operating margin improved to eighteen percent as logistics costs fell.\n\n"
        "## Outlook\n\nManagement expects full year revenue growth to remain in double digits, with capital "
        "expenditure focused on warehouse automation and renewable energy contracts."
    ),
    "cell-biology": (
        "# Cell Biology\n\nMitochondria generate most of the cell's supply of adenosine triphosphate, which "
        "stores chemical energy. Chloroplasts convert light into glucose through the Calvin cycle during "
        "photosynthesis.\n\n## Division\n\nDuring mitosis the chromosomes condense, align at the metaphase "
        "plate and are pulled apart by spindle fibres into two daughter cells."
    ),
    "solar-system": (
        "# The Solar System\n\nJupiter is the largest planet and has a Great Red Spot, a storm that has lasted "
        "for centuries. Saturn is known for its ring system made of ice particles.\n\n## Mars\n\nMars has a thin "
        "carbon dioxide atmosphere and the tallest volcano in the solar system, Olympus Mons."
    ),
    "sourdough-guide": (
        "# Sourdough Bread\n\nA sourdough starter is a fermented culture of flour and water that contains wild "
        "yeast and lactic acid bacteria. Feed the starter daily and keep it at room temperature.\n\n"
        "## Baking\n\nShape the dough, proof it overnight in the refrigerator, then bake in a preheated dutch "
        "oven at high temperature for a crisp crust."
    ),
    "service-agreement": (
        "# Service Agreement\n\nEither party may terminate this agreement with thirty days written notice. "
        "Upon termination the supplier shall return all confidential information and deliver outstanding "
        "invoices.\n\n## Liability\n\nThe supplier's total liability is limited to the fees paid in the twelve "
        "months preceding the claim, excluding gross negligence."
    ),
    "database-indexing": (
        "# Database Indexing\n\nA B-tree index speeds up lookups by keeping keys sorted, at the cost of slower "
        "writes and extra storage. Composite indexes follow the leftmost prefix rule.\n\n## Query Plans\n\nUse "
        "the explain command to inspect the query plan and detect full collection scans."
    ),
}

# (question, expected document)
QUESTIONS: list[tuple[str, str]] = [
    ("How much did revenue grow in Europe?", "annual-report"),
    ("What improved the operating margin?", "annual-report"),
    ("Which organelle produces ATP energy in cells?", "cell-biology"),
    ("What happens to chromosomes during mitosis?", "cell-biology"),
    ("What is the largest planet and its Great Red Spot?", "solar-system"),
    ("Which volcano is the tallest on Mars?", "solar-system"),
    ("How do I keep a sourdough starter alive?", "sourdough-guide"),
    ("How long should the bread proof before baking?", "sourdough-guide"),
    ("How much notice is needed to terminate the agreement?", "service-agreement"),
    ("What limits the supplier's liability?", "service-agreement"),
    ("Why do indexes slow down writes?", "database-indexing"),
    ("How can I detect full collection scans in a query plan?", "database-indexing"),
]
