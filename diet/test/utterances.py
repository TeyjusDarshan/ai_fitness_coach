"""Things clients say about their food, for checking the prompts by hand:

    .venv/bin/python -m diet.dry_run --examples

`expect` says what a good parse looks like (dish, quantity, unit) — read
against the output, not asserted, since the calls are real.
"""

UTTERANCES = [
    # Skipped meals: no dish, but the meal is recorded as skipped.
    {"text": "inniku breakfast skip pannitten, onnum saapdala", "expect": [], "skipped": ["breakfast"]},
    {"text": "kaalaila onnum saapdala, lunch ku rendu chapati", "expect": [("Chapati", 2, "piece")],
     "skipped": ["breakfast"]},
    {"text": "kaalaila moonu idli, oru karandi sambar, konjam thengai chutney saapten",
     "expect": [("Idli", 3, "piece"), ("Sambar", 1, "karandi"), ("Coconut Chutney", 0.5, None)]},
    {"text": "morning rendu dosai with sambar, apram oru tumbler filter coffee sugar pottu",
     "expect": [("Dosa", 2, "piece"), ("Sambar", None, None), ("Filter Coffee", 1, "tumbler")]},
    {"text": "madhiyam rendu karandi sadam, oru karandi paruppu kuzhambu, oru cup beans poriyal, oru cup thayir",
     "expect": [("Cooked Rice", 2, "karandi"), ("Paruppu Kuzhambu", 1, "karandi"),
                ("Beans Poriyal", 1, "cup"), ("Curd", 1, "cup")]},
    {"text": "lunch ku thayir sadam oru plate, oorugai konjam",
     "expect": [("Curd Rice", 1, "plate"), ("Pickle", 0.5, "teaspoon")]},
    {"text": "night moonu chapati, oru cup kurma",
     "expect": [("Chapati", 3, "piece"), ("Vegetable Kurma", 1, "cup")]},
    {"text": "evening oru tumbler tea, rendu Marie biscuit",
     "expect": [("Tea", 1, "tumbler"), ("Marie Biscuit", 2, "piece")]},
    {"text": "காலையில ரெண்டு இட்லி சாப்பிட்டேன், ஒரு டம்ளர் காபி குடிச்சேன்",
     "expect": [("Idli", 2, "piece"), ("Filter Coffee", 1, "tumbler")]},
    {"text": "inniku kaalaila onnum saapidala, madhiyam than oru plate chicken biryani saapten",
     "expect": [("Chicken Biryani", 1, "plate")]},
    {"text": "100 grams paneer, apram 200 ml paal",
     "expect": [("Paneer", 100, "grams"), ("Milk", 200, "ml")]},
    {"text": "arai cup upma, oru vaazhaipazham",
     "expect": [("Upma", 0.5, "cup"), ("Banana", 1, "piece")]},
    {"text": "sambar sadam saapten, appalam rendu",
     "expect": [("Sambar Rice", None, None), ("Appalam", 2, "piece")]},
    {"text": "oru kai pidi verkadalai, oru apple",
     "expect": [("Peanuts", 1, "handful"), ("Apple", 1, "piece")]},
    {"text": "rendu muttai avichu saapten, oru slice bread",
     "expect": [("Boiled Egg", 2, "piece"), ("Bread", 1, "slice")]},
    {"text": "naalu idli nu sonnen, illa illa moonu than saapten",
     "expect": [("Idli", 3, "piece")]},
    {"text": "pasangaluku poori senjen, naan oru karandi ragi kali than saapten keerai kootu oda",
     "expect": [("Ragi Kali", 1, "karandi"), ("Keerai Kootu", None, None)]},
    {"text": "oru spoon nei pottu pongal oru cup, vadai onnu",
     "expect": [("Ven Pongal", 1, "cup"), ("Medu Vadai", 1, "piece")]},
    {"text": "onnarai karandi lemon sadam, niraya thayir pachadi",
     "expect": [("Lemon Rice", 1.5, "karandi"), ("Curd Pachadi", 1.5, None)]},
    {"text": "sundal oru cup, apram elaneer oru glass",
     "expect": [("Sundal", 1, "cup"), ("Tender Coconut Water", 1, "tumbler")]},
    {"text": "meen kuzhambu rendu karandi, meen varuval rendu piece, sadam oru cup",
     "expect": [("Fish Curry", 2, "karandi"), ("Fish Fry", 2, "piece"), ("Cooked Rice", 1, "cup")]},
    {"text": "inniku workout nalla irundhuchu, kaal konjam valikudhu",
     "expect": []},
]
