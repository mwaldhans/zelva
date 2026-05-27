const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const commandsEl = document.getElementById("commands");
const logEl = document.getElementById("log");
const resultEl = document.getElementById("result");
const drawBtn = document.getElementById("drawBtn");
const clearBtn = document.getElementById("clearBtn");
const stopBtn = document.getElementById("stopBtn");
const patternListEl = document.getElementById("patternList");
const patternHint = document.getElementById("patternHint");
const hintToggleBtn = document.getElementById("hintToggleBtn");
const currentPatternEl = document.getElementById("currentPattern");
const speedRangeEl = document.getElementById("speedRange");
const speedValueEl = document.getElementById("speedValue");
const footerSolvedEl = document.getElementById("footerSolved");
const footerRemainingEl = document.getElementById("footerRemaining");
const footerTaskTimeEl = document.getElementById("footerTaskTime");
const footerTotalTimeEl = document.getElementById("footerTotalTime");

const BASE_FRAME_DELAY_MS = 28;
const BASE_COMMAND_DELAY_MS = 170;
const TURTLE_SIZE = 11;
const VISIBLE_SOLUTION_LINES = 2;
const SPEED_STORAGE_KEY = "zelva_draw_speed";
const TARGET_PATTERN_COUNT = 100;
const DRAFT_STORAGE_KEY = "zelva_code_drafts_v1";
const PROGRESS_STORAGE_KEY = "zelva_progress_cache_v1";
const TIME_STORAGE_KEY = "zelva_time_spent_v1";

const CATEGORY_ORDER = ["Zaklady", "Opakovani", "Vzory", "Funkce", "Fraktaly"];

const PATTERNS = [
    { id: "square", category: "Zaklady", name: "1. Ctverec", hint: "Ctverec ma 4 stejne strany a 4 prave uhly. Otoc se 4x o 90 stupnu.", commands: ["forward(100)", "left(90)", "forward(100)", "left(90)", "forward(100)", "left(90)", "forward(100)"] },
    { id: "rectangle", category: "Zaklady", name: "2. Obdelnik", hint: "Obdelnik ma 2 delsi a 2 kratsi strany. Strany se strídají.", commands: ["forward(140)", "left(90)", "forward(80)", "left(90)", "forward(140)", "left(90)", "forward(80)"] },
    { id: "triangle", category: "Zaklady", name: "3. Trojuhelnik", hint: "Rovnostranny trojuhelnik: vnitrni uhel je 60 st., ale zelva se otaci o vnejsi uhel = 180 - 60 = 120 stupnu.", commands: ["left(30)", "forward(120)", "left(120)", "forward(120)", "left(120)", "forward(120)"] },
    { id: "pentagon", category: "Zaklady", name: "4. Petiuhelnik", hint: "Vzorec pro pravidelny n-uhelnik: vnejsi uhel = 360 / n. Pro petiuhelnik: 360 / 5 = 72 stupnu.", commands: ["left(18)", "forward(90)", "left(72)", "forward(90)", "left(72)", "forward(90)", "left(72)", "forward(90)", "left(72)", "forward(90)"] },
    { id: "hexagon", category: "Zaklady", name: "5. Sestiuhelnik", hint: "Sestiuhelnik: vnejsi uhel = 360 / 6 = 60 stupnu. Pouzij stejny vzorec jako pro petiuhelnik.", commands: ["forward(80)", "left(60)", "forward(80)", "left(60)", "forward(80)", "left(60)", "forward(80)", "left(60)", "forward(80)", "left(60)", "forward(80)"] },
    { id: "octagon", category: "Zaklady", name: "6. Osmiuhelnik", hint: "Osmiuhelnik: vnejsi uhel = 360 / 8 = 45 stupnu. Pouzij for i in range(8): forward(...) a left(45).", commands: ["forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)", "left(45)", "forward(60)"] },
    { id: "star", category: "Zaklady", name: "7. Hvezda", hint: "Petiramma hvezda: zelva se otaci o 144 stupnu (ne o 72). Celkem 5 ramen, na zacatku se naklon o 18 st.", commands: ["left(18)", "forward(150)", "right(144)", "forward(150)", "right(144)", "forward(150)", "right(144)", "forward(150)", "right(144)", "forward(150)"] },
    { id: "house", category: "Zaklady", name: "8. Domecek", hint: "Domecek = ctverec + trojuhelnik (strecha). Nakresli ctverec, v rohu se otoc a nakresli rovnostranny trojuhelnik.", commands: ["forward(110)", "left(90)", "forward(80)", "left(90)", "forward(110)", "left(90)", "forward(80)", "left(30)", "forward(64)", "left(120)", "forward(64)"] },
    { id: "stairs", category: "Opakovani", name: "9. Schody", hint: "Schody: kazdy schod = forward + left(90) + forward + right(90). Cely vzor se opakuje - zkus cyklus for i in range(...):", commands: ["forward(40)", "left(90)", "forward(30)", "right(90)", "forward(40)", "left(90)", "forward(30)", "right(90)", "forward(40)", "left(90)", "forward(30)", "right(90)", "forward(40)"] },
    { id: "zigzag", category: "Opakovani", name: "10. Cikcak", hint: "Cikcak: strídej left a right o stejny uhel. Kazdy 'zub' je forward + otoceni.", commands: ["left(35)", "forward(70)", "right(70)", "forward(70)", "left(70)", "forward(70)", "right(70)", "forward(70)", "left(70)", "forward(70)"] },
    { id: "diamond", category: "Opakovani", name: "11. Kosoctverec", hint: "Kosoctverec: jako ctverec, ale nakloneneny. Uhly jsou 60 a 120 stupnu. Zelva zacina naklonena.", commands: ["left(30)", "forward(90)", "left(60)", "forward(90)", "left(120)", "forward(90)", "left(60)", "forward(90)"] },
    { id: "plus", category: "Opakovani", name: "12. Kriz", hint: "Kriz: nakresli svislou usecku, pak penup() + goto(x,y) pro skok na zacatek vodorovne usecky, potom pendown() a kresli.", commands: ["penup()", "goto(360,190)", "pendown()", "forward(100)", "penup()", "goto(310,240)", "pendown()", "right(90)", "forward(100)"] },
    { id: "double_square", category: "Vzory", name: "13. Dvojity ctverec", hint: "Nakresli maly ctverec, pak penup() + goto() a nakresli vetsi ctverec kolem nej. Stred velkeho je totez jako stred maleho.", commands: ["forward(90)", "left(90)", "forward(90)", "left(90)", "forward(90)", "left(90)", "forward(90)", "penup()", "goto(330,210)", "pendown()", "forward(150)", "left(90)", "forward(150)", "left(90)", "forward(150)", "left(90)", "forward(150)"] },
    { id: "square_spiral", category: "Vzory", name: "14. Ctvercova spirala", hint: "Spirala: kazda strana je o krok delsi nez predchozi, otoc se vzdy o 90 st. Vzor: forward(20), left(90), forward(30), left(90), ...", commands: ["forward(20)", "left(90)", "forward(30)", "left(90)", "forward(40)", "left(90)", "forward(50)", "left(90)", "forward(60)", "left(90)", "forward(70)", "left(90)", "forward(80)", "left(90)", "forward(90)"] },
    { id: "flower", category: "Vzory", name: "15. Kvetina", hint: "Kvetina: dva trojuhelniky vedle sebe sdílejí spolecnou stranu. Po prvnim trojuhelniku se otoč o 60 stupnu.", commands: ["forward(80)", "left(120)", "forward(80)", "left(120)", "forward(80)", "left(120)", "right(60)", "forward(80)", "left(120)", "forward(80)", "left(120)", "forward(80)"] },
    { id: "arrow", category: "Vzory", name: "16. Sipka", hint: "Sipka: osa + dva kratsi usecky jako pero. Pouzij penup() + goto() pro presun na spravnou pozici pro kazde pero.", commands: ["forward(120)", "left(150)", "forward(45)", "penup()", "goto(480,240)", "pendown()", "left(60)", "forward(45)"] },
    { id: "hourglass", category: "Vzory", name: "17. Presypaci hodiny", hint: "Presypaci hodiny: ctyri usecky naklonenene o 45 stupnu. Dva trojuhelniky spojene vrcholem.", commands: ["left(45)", "forward(120)", "right(135)", "forward(120)", "right(135)", "forward(120)", "right(135)", "forward(120)"] },
    { id: "flag", category: "Vzory", name: "18. Vlajka", hint: "Vlajka: nejdřiv nakresli svislou tyc (left 90 + forward), pak vlajku jako trojuhelnik vlevo od tyce.", commands: ["left(90)", "forward(140)", "right(90)", "forward(90)", "right(120)", "forward(104)", "right(120)", "forward(104)"] },
    { id: "frame", category: "Vzory", name: "19. Ram", hint: "Ram: nejdřiv velky obdelnik, pak penup() + goto() dovnitr a nakresli mensi obdelnik (okraj rámu).", commands: ["forward(170)", "left(90)", "forward(120)", "left(90)", "forward(170)", "left(90)", "forward(120)", "penup()", "goto(305,185)", "pendown()", "forward(110)", "left(90)", "forward(70)", "left(90)", "forward(110)", "left(90)", "forward(70)"] },
    { id: "letter_z", category: "Vzory", name: "20. Pismeno Z", hint: "Pismeno Z: tri usecky. Horni vodorovná, diagonala dolů doprava, dolní vodorovná. Pouzij goto() nebo natočení.", commands: ["penup()", "goto(300,190)", "pendown()", "forward(140)", "right(135)", "forward(198)", "left(135)", "forward(140)"] },
    { id: "polygon_function", category: "Funkce", name: "25. Funkce: polygon", hint: "Definuj funkci def polygon(): s cyklem uvnitr, pak ji zavolej. Funkce sdruzi opakujici se kroky do jednoho celku, ktery muzes volat vicekrat.", commands: ["def polygon():", "    for i in range(6):", "        forward(70)", "        left(60)", "", "polygon()"] },
    { id: "koch_line", category: "Fraktaly", name: "21. Kochova krivka (uroven 4)", hint: "Koch: kazda usecka se nahradi 4 kratsimi: rovne, zahni doleva, zahni doprava, rovne. Cyklus v cyklu znazornuje hlubsi uroven fraktalu.", commands: ["# Koch motiv ve 4 urovnich", "for l1 in range(2):", "    for l2 in range(2):", "        for l3 in range(2):", "            for l4 in range(2):", "                forward(7)", "                left(60)", "                forward(7)", "                right(120)", "                forward(7)", "                left(60)", "                forward(7)", "            right(120)", "        left(60)", "    right(120)"] },
    {
        id: "snowflake",
        category: "Fraktaly",
        name: "22. Fraktalni vlocka",
        hint: "Fraktalni vlocka: 6 ramen, na konci kazdeho ramene je mensi hvezda a na ni dalsi jeste mensi. Pouzij def s parametrem delky a urovne, rekurze se zastavi kdyz uroven prekroci maximum.",
        commands: [
            "setheading(-90)",
            "forward(100)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "# 1. uroven: 6 ramen + male hvezdy",
            "goto(360,100)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "goto(481,170)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "goto(481,310)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "goto(360,380)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "goto(239,310)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "penup()",
            "goto(360,240)",
            "pendown()",
            "goto(239,170)",
            "setheading(-90)",
            "for i in range(6):",
            "    forward(30)",
            "    backward(30)",
            "    right(60)",
            "# 2. uroven: z kazde vetve jde jedna mensi",
            "penup()",
            "goto(360,100)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(481,170)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(481,310)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(360,380)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(239,310)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(239,170)",
            "pendown()",
            "setheading(-90)",
            "for k in range(6):",
            "    penup()",
            "    forward(30)",
            "    pendown()",
            "    for i in range(6):",
            "        forward(12)",
            "        backward(12)",
            "        right(60)",
            "    penup()",
            "    backward(30)",
            "    right(60)",
            "pendown()",
            "penup()",
            "goto(360,240)",
            "pendown()"
        ]
    },
    { id: "fractal_tree", category: "Fraktaly", name: "23. Strom (vetve se puli)", hint: "Strom: jdi rovne (kmen), pak odboc vlevo a kresli mensi vetev, vrat se, odboc vpravo a kresli druhou vetev, vrat se. S kazdou urovni se delka puli.", commands: ["left(90)", "forward(200)", "left(30)", "forward(100)", "left(28)", "forward(50)", "left(25)", "forward(25)", "backward(25)", "right(50)", "forward(25)", "backward(25)", "left(25)", "backward(50)", "right(56)", "forward(50)", "left(25)", "forward(25)", "backward(25)", "right(50)", "forward(25)", "backward(25)", "left(25)", "backward(50)", "left(28)", "backward(100)", "right(60)", "forward(100)", "left(28)", "forward(50)", "left(25)", "forward(25)", "backward(25)", "right(50)", "forward(25)", "backward(25)", "left(25)", "backward(50)", "right(56)", "forward(50)", "left(25)", "forward(25)", "backward(25)", "right(50)", "forward(25)", "backward(25)", "left(25)", "backward(50)", "left(28)", "backward(100)", "left(30)", "backward(200)"] },
    { id: "sierpinski_hint", category: "Fraktaly", name: "24. Sierpinski styl (uroven 4)", hint: "Sierpinski: trojuhelnik rozdeleny na mensí trojuhelniky. Kazda uroven ma polovicni stranu. Pouzij goto() pro presun na spravnou pozici.", commands: ["# Sierpinski styl: 4 velikosti trojuhelniku", "for lvl1 in range(3):", "    forward(150)", "    left(120)", "for lvl2 in range(3):", "    forward(75)", "    left(120)", "penup()", "goto(322, 262)", "pendown()", "for lvl3 in range(3):", "    forward(38)", "    left(120)", "penup()", "goto(341, 273)", "pendown()", "for lvl4 in range(3):", "    forward(19)", "    left(120)", "penup()", "goto(379, 273)", "pendown()", "for lvl4b in range(3):", "    forward(19)", "    left(120)", "penup()", "goto(360, 240)", "pendown()", "for lvl3b in range(3):", "    forward(38)", "    left(120)"] },
];

function createAutoPattern(patternNumber) {
    if (patternNumber <= 40) {
        const sides = 3 + ((patternNumber - 26) % 7);
        const length = 42 + ((patternNumber - 26) % 6) * 8;
        const turn = (360 / sides).toFixed(2);
        return {
            id: `auto_poly_${patternNumber}`,
            category: "Zaklady",
            name: `${patternNumber}. Polygon ${sides} stran`,
            hint: "Pouzij cyklus pro pravidelny polygon: forward(delka) a left(360/n).",
            commands: [
                `for i in range(${sides}):`,
                `    forward(${length})`,
                `    left(${turn})`,
            ],
        };
    }

    if (patternNumber <= 60) {
        const steps = 6 + ((patternNumber - 41) % 8);
        const base = 24 + ((patternNumber - 41) % 5) * 6;
        const turn = 70 + ((patternNumber - 41) % 5) * 8;
        return {
            id: `auto_cycle_${patternNumber}`,
            category: "Opakovani",
            name: `${patternNumber}. Cyklicky vzor ${patternNumber - 40}`,
            hint: "Opakuj blok prikazu v cyklu, men delku a uhel podle zadaneho vzoru.",
            commands: [
                `for i in range(${steps}):`,
                `    forward(${base})`,
                `    left(${turn})`,
                `    forward(${Math.max(8, Math.round(base / 2))})`,
                `    right(${Math.max(20, Math.round(turn / 2))})`,
            ],
        };
    }

    if (patternNumber <= 80) {
        const petals = 8 + ((patternNumber - 61) % 7);
        const len = 48 + ((patternNumber - 61) % 5) * 10;
        const rot = (360 / petals).toFixed(2);
        return {
            id: `auto_pattern_${patternNumber}`,
            category: "Vzory",
            name: `${patternNumber}. Rozeta ${patternNumber - 60}`,
            hint: "Pouzij dva prikazy forward/backward pro okveti a pak rotaci, cele opakuj v cyklu.",
            commands: [
                `for i in range(${petals}):`,
                `    forward(${len})`,
                `    backward(${len})`,
                `    right(${rot})`,
            ],
        };
    }

    if (patternNumber <= 90) {
        const sides = 3 + ((patternNumber - 81) % 5);
        const len = 30 + ((patternNumber - 81) % 5) * 12;
        const repeat = 4 + ((patternNumber - 81) % 4);
        const turn = (360 / repeat).toFixed(2);
        const sideTurn = (360 / sides).toFixed(2);
        return {
            id: `auto_func_${patternNumber}`,
            category: "Funkce",
            name: `${patternNumber}. Funkce a parametry ${patternNumber - 80}`,
            hint: "Definuj funkci s parametry a volani opakuj v cyklu s ruznymi argumenty.",
            commands: [
                "def poly(delka, n):",
                "    for i in range(n):",
                "        forward(delka)",
                `        left(${sideTurn})`,
                "",
                `for j in range(${repeat}):`,
                `    poly(${len}, ${sides})`,
                `    right(${turn})`,
            ],
        };
    }

    const levelLimit = 3 + ((patternNumber - 91) % 2);
    const startLen = 90 + ((patternNumber - 91) % 3) * 15;
    const angle = 18 + ((patternNumber - 91) % 4) * 6;
    return {
        id: `auto_recur_${patternNumber}`,
        category: "Fraktaly",
        name: `${patternNumber}. Rekurzivni vetveni ${patternNumber - 90}`,
        hint: "V rekurzi dej podminku if pro zastaveni a zmensuj delku pri kazdem dalsim volani.",
        commands: [
            "left(90)",
            "def vetev(delka, uroven):",
            `    if uroven < ${levelLimit}:`,
            "        forward(delka)",
            `        left(${angle})`,
            "        vetev(delka*0.67, uroven+1)",
            `        right(${angle * 2})`,
            "        vetev(delka*0.67, uroven+1)",
            `        left(${angle})`,
            "        backward(delka)",
            "",
            `vetev(${startLen}, 0)`,
        ],
    };
}

while (PATTERNS.length < TARGET_PATTERN_COUNT) {
    const number = PATTERNS.length + 1;
    PATTERNS.push(createAutoPattern(number));
}

const state = createInitialState();
const segments = [];
const progressByPattern = new Map();
let expectedSegments = [];
let selectedPatternId = PATTERNS[0].id;
let isRunning = false;
let cancelRequested = false;
let drawSpeed = 5;
const collapsedCategories = new Set(CATEGORY_ORDER);
let draftSaveTimer = null;
const draftByPattern = new Map();
const timeSpentByPattern = new Map();
let activePatternId = null;
let activePatternStartedAt = 0;
let footerTicker = null;

const HINT_STORAGE_KEY = "zelva_hints_used";
const hintUsedByPattern = new Map();

function loadHintUsage() {
    try {
        const raw = localStorage.getItem(HINT_STORAGE_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            for (const [k, v] of Object.entries(parsed)) {
                hintUsedByPattern.set(k, v);
            }
        }
    } catch (_) {
        // Ignore storage issues.
    }
}

function saveHintUsage(patternId) {
    hintUsedByPattern.set(patternId, true);
    try {
        const obj = Object.fromEntries(hintUsedByPattern);
        localStorage.setItem(HINT_STORAGE_KEY, JSON.stringify(obj));
    } catch (_) {
        // Ignore storage issues.
    }
}

function loadProgressCache() {
    try {
        const raw = localStorage.getItem(PROGRESS_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        for (const [patternId, value] of Object.entries(parsed)) {
            if (!value || typeof value !== "object") {
                continue;
            }
            const record = {
                pattern_id: patternId,
                solution_text: typeof value.solution_text === "string" ? value.solution_text : "",
                solved: Boolean(value.solved),
                score: Number(value.score) || 0,
            };
            progressByPattern.set(patternId, record);
            draftByPattern.set(patternId, record.solution_text);
        }
    } catch (_) {
        // Ignore malformed local data.
    }
}

function loadTimeStorage() {
    try {
        const raw = localStorage.getItem(TIME_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        for (const [patternId, value] of Object.entries(parsed)) {
            const seconds = Number(value) || 0;
            if (seconds > 0) {
                timeSpentByPattern.set(patternId, Math.floor(seconds));
            }
        }
    } catch (_) {
        // Ignore malformed local data.
    }
}

function saveTimeStorage() {
    try {
        localStorage.setItem(TIME_STORAGE_KEY, JSON.stringify(Object.fromEntries(timeSpentByPattern)));
    } catch (_) {
        // Ignore storage quota/errors.
    }
}

function formatDuration(totalSeconds) {
    const safe = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(safe / 3600);
    const minutes = Math.floor((safe % 3600) / 60);
    const seconds = safe % 60;
    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function isPatternSolved(patternId) {
    return Boolean(progressByPattern.get(patternId)?.solved);
}

function getTaskElapsedSeconds(patternId) {
    const persisted = Number(timeSpentByPattern.get(patternId) || 0);
    if (isPatternSolved(patternId)) {
        return persisted;
    }
    if (patternId !== activePatternId || !activePatternStartedAt) {
        return persisted;
    }
    const activeSeconds = Math.floor((Date.now() - activePatternStartedAt) / 1000);
    return persisted + Math.max(0, activeSeconds);
}

function getTotalElapsedSeconds() {
    let total = 0;
    for (const pattern of PATTERNS) {
        total += getTaskElapsedSeconds(pattern.id);
    }
    return total;
}

function updateFooterStats() {
    const solvedCount = PATTERNS.filter((pattern) => Boolean(progressByPattern.get(pattern.id)?.solved)).length;
    const totalCount = PATTERNS.length;
    const remainingCount = Math.max(0, totalCount - solvedCount);
    const currentTaskSeconds = getTaskElapsedSeconds(selectedPatternId);
    const totalSeconds = getTotalElapsedSeconds();

    if (footerSolvedEl) {
        footerSolvedEl.textContent = `Hotovo: ${solvedCount}/${totalCount}`;
    }
    if (footerRemainingEl) {
        footerRemainingEl.textContent = `Zbyva: ${remainingCount}`;
    }
    if (footerTaskTimeEl) {
        footerTaskTimeEl.textContent = `Cas ulohy: ${formatDuration(currentTaskSeconds)}`;
    }
    if (footerTotalTimeEl) {
        footerTotalTimeEl.textContent = `Celkem: ${formatDuration(totalSeconds)}`;
    }
}

function flushActiveTaskTime(stopTimer = false) {
    if (!activePatternId || !activePatternStartedAt) {
        return;
    }
    if (isPatternSolved(activePatternId)) {
        activePatternStartedAt = stopTimer ? 0 : Date.now();
        updateFooterStats();
        return;
    }
    const deltaSeconds = Math.floor((Date.now() - activePatternStartedAt) / 1000);
    if (deltaSeconds > 0) {
        const previous = Number(timeSpentByPattern.get(activePatternId) || 0);
        timeSpentByPattern.set(activePatternId, previous + deltaSeconds);
        saveTimeStorage();
    }
    activePatternStartedAt = stopTimer ? 0 : Date.now();
    updateFooterStats();
}

function ensureFooterTicker() {
    if (footerTicker) {
        return;
    }
    footerTicker = setInterval(() => {
        updateFooterStats();
    }, 1000);
}

function startTaskTimer(patternId) {
    if (!patternId) {
        return;
    }
    flushActiveTaskTime(true);
    activePatternId = patternId;
    activePatternStartedAt = isPatternSolved(patternId) ? 0 : Date.now();
    ensureFooterTicker();
    updateFooterStats();
}

function saveProgressCache() {
    try {
        localStorage.setItem(PROGRESS_STORAGE_KEY, JSON.stringify(Object.fromEntries(progressByPattern)));
    } catch (_) {
        // Ignore storage quota/errors.
    }
}

function loadDraftStorage() {
    try {
        const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        for (const [patternId, solutionText] of Object.entries(parsed)) {
            draftByPattern.set(patternId, String(solutionText));
        }
    } catch (_) {
        // Ignore malformed local data.
    }
}

function saveDraftStorage() {
    try {
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(Object.fromEntries(draftByPattern)));
    } catch (_) {
        // Ignore storage quota/errors.
    }
}

function setLocalDraft(patternId, solutionText) {
    if (!patternId) {
        return;
    }
    draftByPattern.set(patternId, solutionText);
    saveDraftStorage();
}

function createInitialState() {
    return {
        x: canvas.width / 2,
        y: canvas.height / 2,
        angle: 0,
        penDown: true,
    };
}

function resetTurtleState() {
    const initial = createInitialState();
    state.x = initial.x;
    state.y = initial.y;
    state.angle = initial.angle;
    state.penDown = initial.penDown;
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function sleepInterruptible(ms) {
    const waitMs = Math.max(0, Math.round(ms));
    if (waitMs === 0) {
        return cancelRequested;
    }

    const CHUNK_MS = 20;
    let elapsed = 0;
    while (elapsed < waitMs) {
        if (cancelRequested) {
            return true;
        }
        const chunk = Math.min(CHUNK_MS, waitMs - elapsed);
        await sleep(chunk);
        elapsed += chunk;
    }
    return cancelRequested;
}

function clampSpeed(rawSpeed) {
    const numeric = Number(rawSpeed);
    if (!Number.isFinite(numeric)) {
        return 5;
    }
    return Math.min(10, Math.max(1, Math.round(numeric)));
}

function getSpeedFactor() {
    // 1 => very slow, 10 => very fast
    return 0.02 + ((11 - drawSpeed) / 9) * 1.98;
}

function getFrameDelay() {
    return Math.max(0, Math.round(BASE_FRAME_DELAY_MS * getSpeedFactor()));
}

function getCommandDelay() {
    return Math.max(0, Math.round(BASE_COMMAND_DELAY_MS * getSpeedFactor()));
}

function getAnimationStepDistance() {
    const boost = (drawSpeed - 1) / 9;
    return 8 + boost * 56;
}

function renderSpeedValue() {
    if (speedValueEl) {
        speedValueEl.textContent = `${drawSpeed} / 10`;
    }
}

function setDrawSpeed(newSpeed) {
    drawSpeed = clampSpeed(newSpeed);
    if (speedRangeEl) {
        speedRangeEl.value = String(drawSpeed);
    }
    renderSpeedValue();
    try {
        localStorage.setItem(SPEED_STORAGE_KEY, String(drawSpeed));
    } catch (_) {
        // Ignore localStorage issues.
    }
}

function initSpeedControl() {
    let savedSpeed = null;
    try {
        savedSpeed = localStorage.getItem(SPEED_STORAGE_KEY);
    } catch (_) {
        // Ignore localStorage issues.
    }
    const initialSpeed = savedSpeed ?? (speedRangeEl ? speedRangeEl.value : 5);
    setDrawSpeed(initialSpeed);

    if (speedRangeEl) {
        speedRangeEl.addEventListener("input", () => {
            setDrawSpeed(speedRangeEl.value);
        });
    }
}

function toRadians(deg) {
    return (deg * Math.PI) / 180;
}

function segmentLength(segment) {
    return Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1);
}

function normalizeCommandName(inputName) {
    const command = inputName.startsWith("turtle.") ? inputName.slice(7) : inputName;
    const aliases = {
        forward: "forward",
        fd: "forward",
        backward: "backward",
        back: "backward",
        bk: "backward",
        left: "left",
        lt: "left",
        right: "right",
        rt: "right",
        penup: "penup",
        pu: "penup",
        up: "penup",
        pendown: "pendown",
        pd: "pendown",
        down: "pendown",
        goto: "goto",
        setpos: "goto",
        setposition: "goto",
        setheading: "setheading",
        seth: "setheading",
        home: "home",
    };

    return aliases[command] || null;
}

function parseCommand(rawLine, lineNumber) {
    const raw = rawLine.trim();
    if (!raw) {
        return { skip: true };
    }

    const match = raw.match(/^([a-z_][a-z0-9_\.]*)\s*(?:\(([^)]*)\))?$/i);
    if (!match) {
        return { error: `Neplatny prikaz na radku ${lineNumber}: ${raw}` };
    }

    const command = normalizeCommandName(match[1].toLowerCase());
    if (!command) {
        return { error: `Neznamy prikaz na radku ${lineNumber}: ${raw}` };
    }

    const args = (match[2] || "")
        .split(",")
        .map((x) => x.trim())
        .filter((x) => x.length > 0)
        .map((x) => Number(x));

    if (args.some((x) => Number.isNaN(x))) {
        return { error: `Neplatne cislo na radku ${lineNumber}: ${raw}` };
    }

    return { command, args, raw };
}

function handleEditorIndentation(event) {
    if (event.key !== "Tab") {
        return;
    }

    event.preventDefault();
    const indent = "    ";
    const start = commandsEl.selectionStart;
    const end = commandsEl.selectionEnd;
    const value = commandsEl.value;

    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const lineEnd = value.indexOf("\n", end);
    const selectedEnd = lineEnd === -1 ? value.length : lineEnd;
    const selectedText = value.slice(lineStart, selectedEnd);
    const lines = selectedText.split("\n");

    if (event.shiftKey) {
        let removedTotal = 0;
        const outdentedLines = lines.map((line) => {
            if (line.startsWith(indent)) {
                removedTotal += indent.length;
                return line.slice(indent.length);
            }
            if (line.startsWith("\t")) {
                removedTotal += 1;
                return line.slice(1);
            }
            return line;
        });

        const updated = outdentedLines.join("\n");
        commandsEl.value = value.slice(0, lineStart) + updated + value.slice(selectedEnd);

        if (start === end) {
            const removedAtCursor = lines[0].startsWith(indent) ? indent.length : (lines[0].startsWith("\t") ? 1 : 0);
            const newPos = Math.max(lineStart, start - removedAtCursor);
            commandsEl.selectionStart = newPos;
            commandsEl.selectionEnd = newPos;
            return;
        }

        commandsEl.selectionStart = lineStart;
        commandsEl.selectionEnd = Math.max(lineStart, selectedEnd - removedTotal);
        return;
    }

    const indentedLines = lines.map((line) => indent + line);
    const updated = indentedLines.join("\n");
    commandsEl.value = value.slice(0, lineStart) + updated + value.slice(selectedEnd);

    if (start === end) {
        const newPos = start + indent.length;
        commandsEl.selectionStart = newPos;
        commandsEl.selectionEnd = newPos;
        return;
    }

    commandsEl.selectionStart = lineStart;
    commandsEl.selectionEnd = selectedEnd + indent.length * lines.length;
}

function expandProgramLines(rawLines) {
    const functionDefs = new Map();
    const MAX_CALL_DEPTH = 80;

    function splitArgs(argText) {
        const text = (argText || "").trim();
        if (!text) {
            return [];
        }

        const args = [];
        let depth = 0;
        let start = 0;
        for (let i = 0; i < text.length; i += 1) {
            const ch = text[i];
            if (ch === "(") {
                depth += 1;
            } else if (ch === ")") {
                depth -= 1;
                if (depth < 0) {
                    return null;
                }
            } else if (ch === "," && depth === 0) {
                args.push(text.slice(start, i).trim());
                start = i + 1;
            }
        }

        if (depth !== 0) {
            return null;
        }

        args.push(text.slice(start).trim());
        return args.filter((part) => part.length > 0);
    }

    function tokenizeExpression(expr) {
        const tokens = [];
        let i = 0;
        while (i < expr.length) {
            const ch = expr[i];
            if (/\s/.test(ch)) {
                i += 1;
                continue;
            }
            if (/[0-9.]/.test(ch)) {
                let j = i + 1;
                while (j < expr.length && /[0-9.]/.test(expr[j])) {
                    j += 1;
                }
                const numberText = expr.slice(i, j);
                if (!/^(\d+\.?\d*|\d*\.\d+)$/.test(numberText)) {
                    return { ok: false, error: `Neplatne cislo '${numberText}'.` };
                }
                tokens.push({ type: "number", value: Number(numberText) });
                i = j;
                continue;
            }
            if (/[a-zA-Z_]/.test(ch)) {
                let j = i + 1;
                while (j < expr.length && /[a-zA-Z0-9_]/.test(expr[j])) {
                    j += 1;
                }
                tokens.push({ type: "identifier", value: expr.slice(i, j) });
                i = j;
                continue;
            }
            if ("+-*/()".includes(ch)) {
                tokens.push({ type: "operator", value: ch });
                i += 1;
                continue;
            }
            return { ok: false, error: `Neznamy znak '${ch}' ve vyrazu.` };
        }
        return { ok: true, tokens };
    }

    function evaluateExpression(expr, env) {
        const tokenized = tokenizeExpression((expr || "").trim());
        if (!tokenized.ok) {
            return tokenized;
        }
        const tokens = tokenized.tokens;
        let pos = 0;

        function parsePrimary() {
            const token = tokens[pos];
            if (!token) {
                return { ok: false, error: "Necekany konec vyrazu." };
            }

            if (token.type === "number") {
                pos += 1;
                return { ok: true, value: token.value };
            }

            if (token.type === "identifier") {
                if (!env.has(token.value)) {
                    return { ok: false, error: `Neznama promenna '${token.value}'.` };
                }
                pos += 1;
                return { ok: true, value: env.get(token.value) };
            }

            if (token.type === "operator" && token.value === "(") {
                pos += 1;
                const inner = parseAddSub();
                if (!inner.ok) {
                    return inner;
                }
                const close = tokens[pos];
                if (!close || close.type !== "operator" || close.value !== ")") {
                    return { ok: false, error: "Chybi ')' ve vyrazu." };
                }
                pos += 1;
                return inner;
            }

            return { ok: false, error: `Necekavany token '${token.value}'.` };
        }

        function parseUnary() {
            const token = tokens[pos];
            if (token && token.type === "operator" && (token.value === "+" || token.value === "-")) {
                pos += 1;
                const value = parseUnary();
                if (!value.ok) {
                    return value;
                }
                return { ok: true, value: token.value === "-" ? -value.value : value.value };
            }
            return parsePrimary();
        }

        function parseMulDiv() {
            let left = parseUnary();
            if (!left.ok) {
                return left;
            }
            while (true) {
                const token = tokens[pos];
                if (!token || token.type !== "operator" || (token.value !== "*" && token.value !== "/")) {
                    return left;
                }
                pos += 1;
                const right = parseUnary();
                if (!right.ok) {
                    return right;
                }
                if (token.value === "/" && right.value === 0) {
                    return { ok: false, error: "Deleni nulou." };
                }
                left = { ok: true, value: token.value === "*" ? left.value * right.value : left.value / right.value };
            }
        }

        function parseAddSub() {
            let left = parseMulDiv();
            if (!left.ok) {
                return left;
            }
            while (true) {
                const token = tokens[pos];
                if (!token || token.type !== "operator" || (token.value !== "+" && token.value !== "-")) {
                    return left;
                }
                pos += 1;
                const right = parseMulDiv();
                if (!right.ok) {
                    return right;
                }
                left = { ok: true, value: token.value === "+" ? left.value + right.value : left.value - right.value };
            }
        }

        const parsed = parseAddSub();
        if (!parsed.ok) {
            return parsed;
        }
        if (pos !== tokens.length) {
            return { ok: false, error: `Neplatny vyraz u '${tokens[pos].value}'.` };
        }
        if (!Number.isFinite(parsed.value)) {
            return { ok: false, error: "Vysledkem vyrazu neni konecne cislo." };
        }
        return parsed;
    }

    function evaluateCondition(condText, env) {
        const comparatorMatch = condText.match(/^(.*?)(<=|>=|==|!=|<|>)(.*)$/);
        if (!comparatorMatch) {
            const value = evaluateExpression(condText, env);
            if (!value.ok) {
                return value;
            }
            return { ok: true, value: value.value !== 0 };
        }

        const left = evaluateExpression(comparatorMatch[1].trim(), env);
        if (!left.ok) {
            return left;
        }
        const right = evaluateExpression(comparatorMatch[3].trim(), env);
        if (!right.ok) {
            return right;
        }

        const op = comparatorMatch[2];
        if (op === "<") {
            return { ok: true, value: left.value < right.value };
        }
        if (op === ">") {
            return { ok: true, value: left.value > right.value };
        }
        if (op === "<=") {
            return { ok: true, value: left.value <= right.value };
        }
        if (op === ">=") {
            return { ok: true, value: left.value >= right.value };
        }
        if (op === "==") {
            return { ok: true, value: left.value === right.value };
        }
        return { ok: true, value: left.value !== right.value };
    }

    function isValidIdentifier(name) {
        return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name);
    }

    function getIndent(line) {
        let count = 0;
        for (const ch of line) {
            if (ch === " ") {
                count += 1;
            } else if (ch === "\t") {
                count += 4;
            } else {
                break;
            }
        }
        return count;
    }

    function findNextNonEmpty(startIndex, stopIndex = rawLines.length) {
        for (let i = startIndex; i < stopIndex; i += 1) {
            const trimmed = rawLines[i].trim();
            if (trimmed && !trimmed.startsWith("#")) {
                return i;
            }
        }
        return -1;
    }

    function findBlockEnd(startIndex, indentLevel, stopIndex = rawLines.length) {
        for (let i = startIndex; i < stopIndex; i += 1) {
            const raw = rawLines[i].trim();
            if (!raw || raw.startsWith("#")) {
                continue;
            }
            const indent = getIndent(rawLines[i]);
            if (indent < indentLevel) {
                return i;
            }
        }
        return stopIndex;
    }

    function renderCommandWithValues(raw, env, lineNumber) {
        const match = raw.match(/^([a-z_][a-z0-9_\.]*)\s*(?:\((.*)\))?$/i);
        if (!match) {
            return { ok: true, text: raw };
        }

        const commandName = match[1];
        const argsText = match[2];
        if (typeof argsText === "undefined") {
            return { ok: true, text: raw };
        }

        const args = splitArgs(argsText);
        if (args === null) {
            return { ok: false, error: `Neplatne argumenty na radku ${lineNumber}.` };
        }

        const evaluated = [];
        for (const argExpr of args) {
            const value = evaluateExpression(argExpr, env);
            if (!value.ok) {
                return { ok: false, error: `${value.error} (radek ${lineNumber})` };
            }
            evaluated.push(value.value);
        }

        if (evaluated.length === 0) {
            return { ok: true, text: `${commandName}()` };
        }
        return { ok: true, text: `${commandName}(${evaluated.join(", ")})` };
    }

    function parseBlock(startIndex, indentLevel, env = new Map(), callStack = [], stopIndex = rawLines.length) {
        const expanded = [];

        for (let i = startIndex; i < stopIndex; i += 1) {
            const line = rawLines[i];
            const raw = line.trim();
            if (!raw || raw.startsWith("#")) {
                continue;
            }

            const indent = getIndent(line);
            if (indent < indentLevel) {
                return { ok: true, lines: expanded, nextIndex: i };
            }
            if (indent > indentLevel) {
                return { ok: false, error: `Neocekavane odsazeni na radku ${i + 1}.` };
            }

            const loopMatch = raw.match(/^for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+range\(\s*(.+)\s*\)\s*:\s*$/);
            if (loopMatch) {
                const loopVar = loopMatch[1];
                const countEval = evaluateExpression(loopMatch[2], env);
                if (!countEval.ok) {
                    return { ok: false, error: `${countEval.error} (radek ${i + 1})` };
                }
                const count = Math.max(0, Math.floor(countEval.value));
                const childStart = findNextNonEmpty(i + 1, stopIndex);
                if (childStart === -1) {
                    return { ok: false, error: `Chybi telo cyklu na radku ${i + 1}.` };
                }

                const childIndent = getIndent(rawLines[childStart]);
                if (childIndent <= indentLevel) {
                    return { ok: false, error: `Po cyklu na radku ${i + 1} chybi odsazeny blok.` };
                }

                const blockEnd = findBlockEnd(childStart, childIndent, stopIndex);
                for (let r = 0; r < count; r += 1) {
                    const loopEnv = new Map(env);
                    loopEnv.set(loopVar, r);
                    const nested = parseBlock(childStart, childIndent, loopEnv, callStack, blockEnd);
                    if (!nested.ok) {
                        return nested;
                    }
                    for (const cmd of nested.lines) {
                        expanded.push({ ...cmd });
                    }
                }
                i = blockEnd - 1;
                continue;
            }

            const ifMatch = raw.match(/^if\s+(.+)\s*:\s*$/);
            if (ifMatch) {
                const condition = evaluateCondition(ifMatch[1], env);
                if (!condition.ok) {
                    return { ok: false, error: `${condition.error} (radek ${i + 1})` };
                }

                const ifStart = findNextNonEmpty(i + 1, stopIndex);
                if (ifStart === -1) {
                    return { ok: false, error: `Chybi telo podminky na radku ${i + 1}.` };
                }

                const ifIndent = getIndent(rawLines[ifStart]);
                if (ifIndent <= indentLevel) {
                    return { ok: false, error: `Po if na radku ${i + 1} chybi odsazeny blok.` };
                }

                const ifEnd = findBlockEnd(ifStart, ifIndent, stopIndex);
                let elseStart = -1;
                let elseIndent = -1;
                let elseEnd = -1;
                const maybeElse = findNextNonEmpty(ifEnd, stopIndex);
                if (maybeElse !== -1) {
                    const elseRaw = rawLines[maybeElse].trim();
                    const elseLineIndent = getIndent(rawLines[maybeElse]);
                    if (elseLineIndent === indentLevel && /^else\s*:\s*$/.test(elseRaw)) {
                        elseStart = findNextNonEmpty(maybeElse + 1, stopIndex);
                        if (elseStart === -1) {
                            return { ok: false, error: `Po else na radku ${maybeElse + 1} chybi odsazeny blok.` };
                        }
                        elseIndent = getIndent(rawLines[elseStart]);
                        if (elseIndent <= indentLevel) {
                            return { ok: false, error: `Po else na radku ${maybeElse + 1} chybi odsazeny blok.` };
                        }
                        elseEnd = findBlockEnd(elseStart, elseIndent, stopIndex);
                    }
                }

                if (condition.value) {
                    const chosen = parseBlock(ifStart, ifIndent, env, callStack, ifEnd);
                    if (!chosen.ok) {
                        return chosen;
                    }
                    for (const cmd of chosen.lines) {
                        expanded.push({ ...cmd });
                    }
                } else if (elseStart !== -1) {
                    const chosen = parseBlock(elseStart, elseIndent, env, callStack, elseEnd);
                    if (!chosen.ok) {
                        return chosen;
                    }
                    for (const cmd of chosen.lines) {
                        expanded.push({ ...cmd });
                    }
                }

                i = (elseEnd !== -1 ? elseEnd : ifEnd) - 1;
                continue;
            }

            const functionDefMatch = raw.match(/^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(([^)]*)\)\s*:\s*$/);
            if (functionDefMatch) {
                const functionName = functionDefMatch[1];
                const paramsText = functionDefMatch[2] || "";
                const params = splitArgs(paramsText);
                if (params === null) {
                    return { ok: false, error: `Neplatna definice parametru na radku ${i + 1}.` };
                }
                for (const param of params) {
                    if (!isValidIdentifier(param)) {
                        return { ok: false, error: `Neplatny parametr funkce '${param}' na radku ${i + 1}.` };
                    }
                }
                if (new Set(params).size !== params.length) {
                    return { ok: false, error: `Duplicitni parametr ve funkci '${functionName}' na radku ${i + 1}.` };
                }

                const childStart = findNextNonEmpty(i + 1, stopIndex);
                if (childStart === -1) {
                    return { ok: false, error: `Chybi telo funkce na radku ${i + 1}.` };
                }

                const childIndent = getIndent(rawLines[childStart]);
                if (childIndent <= indentLevel) {
                    return { ok: false, error: `Po definici funkce na radku ${i + 1} chybi odsazeny blok.` };
                }

                const bodyEnd = findBlockEnd(childStart, childIndent, stopIndex);

                functionDefs.set(functionName, {
                    params,
                    bodyStart: childStart,
                    bodyIndent: childIndent,
                    bodyEnd,
                });
                i = bodyEnd - 1;
                continue;
            }

            const functionCallMatch = raw.match(/^([a-zA-Z_][a-zA-Z0-9_]*)\(([^)]*)\)\s*$/);
            if (functionCallMatch && functionDefs.has(functionCallMatch[1])) {
                const functionName = functionCallMatch[1];
                const fnDef = functionDefs.get(functionName);
                if (!fnDef) {
                    return { ok: false, error: `Neznama funkce '${functionName}' na radku ${i + 1}.` };
                }

                if (callStack.length >= MAX_CALL_DEPTH) {
                    return { ok: false, error: `Prilis hluboke volani funkce '${functionName}' (radek ${i + 1}).` };
                }

                const callArgs = splitArgs(functionCallMatch[2] || "");
                if (callArgs === null) {
                    return { ok: false, error: `Neplatne argumenty funkce '${functionName}' na radku ${i + 1}.` };
                }
                if (callArgs.length !== fnDef.params.length) {
                    return {
                        ok: false,
                        error: `Funkce '${functionName}' ocekava ${fnDef.params.length} parametru, ale dostala ${callArgs.length} (radek ${i + 1}).`,
                    };
                }

                const scope = new Map(env);
                for (let idx = 0; idx < fnDef.params.length; idx += 1) {
                    const argEval = evaluateExpression(callArgs[idx], env);
                    if (!argEval.ok) {
                        return { ok: false, error: `${argEval.error} (radek ${i + 1})` };
                    }
                    scope.set(fnDef.params[idx], argEval.value);
                }

                const nested = parseBlock(
                    fnDef.bodyStart,
                    fnDef.bodyIndent,
                    scope,
                    [...callStack, functionName],
                    fnDef.bodyEnd,
                );
                if (!nested.ok) {
                    return nested;
                }
                for (const cmd of nested.lines) {
                    expanded.push({ ...cmd });
                }
                continue;
            }

            if (/^else\s*:\s*$/.test(raw)) {
                return { ok: false, error: `Necekavane else na radku ${i + 1}.` };
            }

            const rendered = renderCommandWithValues(raw, env, i + 1);
            if (!rendered.ok) {
                return { ok: false, error: rendered.error };
            }

            expanded.push({ text: rendered.text, lineNumber: i + 1 });
        }

        return { ok: true, lines: expanded, nextIndex: stopIndex };
    }

    const top = parseBlock(0, 0, new Map(), []);
    if (!top.ok) {
        return top;
    }
    return { ok: true, lines: top.lines };
}

function drawCursor() {
    const angle = toRadians(state.angle);
    const tipX = state.x + Math.cos(angle) * TURTLE_SIZE;
    const tipY = state.y + Math.sin(angle) * TURTLE_SIZE;
    const leftX = state.x + Math.cos(angle + 2.4) * TURTLE_SIZE;
    const leftY = state.y + Math.sin(angle + 2.4) * TURTLE_SIZE;
    const rightX = state.x + Math.cos(angle - 2.4) * TURTLE_SIZE;
    const rightY = state.y + Math.sin(angle - 2.4) * TURTLE_SIZE;

    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(leftX, leftY);
    ctx.lineTo(rightX, rightY);
    ctx.closePath();
    ctx.fillStyle = "#f28f3b";
    ctx.fill();
    ctx.strokeStyle = "#a45417";
    ctx.lineWidth = 1.5;
    ctx.stroke();
}

function drawSegments(segmentList, color, width) {
    for (const segment of segmentList) {
        ctx.beginPath();
        ctx.moveTo(segment.x1, segment.y1);
        ctx.lineTo(segment.x2, segment.y2);
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.stroke();
    }
}

function renderScene(tempSegment = null) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawSegments(expectedSegments, "#e7ebf0", 3);
    drawSegments(segments, "#0e7c66", 2);
    if (tempSegment) {
        drawSegments([tempSegment], "#0e7c66", 2);
    }
    drawCursor();
}

function distancePointToSegment(px, py, segment) {
    const vx = segment.x2 - segment.x1;
    const vy = segment.y2 - segment.y1;
    const wx = px - segment.x1;
    const wy = py - segment.y1;
    const c1 = vx * wx + vy * wy;
    if (c1 <= 0) {
        return Math.hypot(px - segment.x1, py - segment.y1);
    }
    const c2 = vx * vx + vy * vy;
    if (c2 <= c1) {
        return Math.hypot(px - segment.x2, py - segment.y2);
    }
    const ratio = c1 / c2;
    const projX = segment.x1 + ratio * vx;
    const projY = segment.y1 + ratio * vy;
    return Math.hypot(px - projX, py - projY);
}

function averageMinDistance(sampleSegments, targetSegments) {
    if (sampleSegments.length === 0 || targetSegments.length === 0) {
        return Number.POSITIVE_INFINITY;
    }
    const STEP = 5;
    let totalDist = 0;
    let count = 0;

    for (const seg of sampleSegments) {
        const length = segmentLength(seg);
        const steps = Math.max(1, Math.ceil(length / STEP));
        for (let i = 0; i <= steps; i += 1) {
            const t = i / steps;
            const px = seg.x1 + (seg.x2 - seg.x1) * t;
            const py = seg.y1 + (seg.y2 - seg.y1) * t;
            let best = Number.POSITIVE_INFINITY;
            for (const target of targetSegments) {
                const dist = distancePointToSegment(px, py, target);
                if (dist < best) {
                    best = dist;
                }
            }
            totalDist += best;
            count += 1;
        }
    }

    return count > 0 ? totalDist / count : Number.POSITIVE_INFINITY;
}

function evaluateDrawing() {
    if (segments.length === 0) {
        return { isMatch: false, score: 0, reason: "Nic neni nakresleno." };
    }
    if (expectedSegments.length === 0) {
        return { isMatch: false, score: 0, reason: "Vybrany vzor nema referenci." };
    }

    const expectedToUser = averageMinDistance(expectedSegments, segments);
    const userToExpected = averageMinDistance(segments, expectedSegments);
    const avgExpectedLen = expectedSegments.reduce((sum, seg) => sum + segmentLength(seg), 0) / expectedSegments.length;
    const baseTolerance = Math.max(5, Math.min(14, avgExpectedLen * 0.11));
    const meanDist = (expectedToUser + userToExpected) / 2;
    const score = Math.max(0, Math.min(1, 1 - meanDist / (baseTolerance * 2.3)));
    const isMatch = expectedToUser <= baseTolerance && userToExpected <= baseTolerance * 1.4;

    return {
        isMatch,
        score,
        reason: isMatch ? "Stejne jako vzor." : "Neni to stejne jako vzor.",
    };
}

function clearResults() {
    logEl.textContent = "";
    resultEl.textContent = "";
    resultEl.className = "result";
}

function resetCanvas() {
    segments.length = 0;
    resetTurtleState();
    clearResults();
    renderScene();
}

function applyCommandToSimulation(simState, simSegments, command, args) {
    if (command === "forward" && args.length === 1) {
        const endX = simState.x + args[0] * Math.cos(toRadians(simState.angle));
        const endY = simState.y + args[0] * Math.sin(toRadians(simState.angle));
        if (simState.penDown) {
            simSegments.push({ x1: simState.x, y1: simState.y, x2: endX, y2: endY });
        }
        simState.x = endX;
        simState.y = endY;
        return null;
    }
    if (command === "backward" && args.length === 1) {
        const endX = simState.x - args[0] * Math.cos(toRadians(simState.angle));
        const endY = simState.y - args[0] * Math.sin(toRadians(simState.angle));
        if (simState.penDown) {
            simSegments.push({ x1: simState.x, y1: simState.y, x2: endX, y2: endY });
        }
        simState.x = endX;
        simState.y = endY;
        return null;
    }
    if (command === "left" && args.length === 1) {
        simState.angle -= args[0];
        return null;
    }
    if (command === "right" && args.length === 1) {
        simState.angle += args[0];
        return null;
    }
    if (command === "penup" && args.length === 0) {
        simState.penDown = false;
        return null;
    }
    if (command === "pendown" && args.length === 0) {
        simState.penDown = true;
        return null;
    }
    if (command === "goto" && args.length === 2) {
        if (simState.penDown) {
            simSegments.push({ x1: simState.x, y1: simState.y, x2: args[0], y2: args[1] });
        }
        simState.x = args[0];
        simState.y = args[1];
        return null;
    }
    if (command === "setheading" && args.length === 1) {
        simState.angle = args[0];
        return null;
    }
    if (command === "home" && args.length === 0) {
        const initial = createInitialState();
        if (simState.penDown) {
            simSegments.push({ x1: simState.x, y1: simState.y, x2: initial.x, y2: initial.y });
        }
        simState.x = initial.x;
        simState.y = initial.y;
        simState.angle = initial.angle;
        return null;
    }
    return "Neznamy nebo spatny format prikazu.";
}

function buildExpectedSegments(pattern) {
    const simState = createInitialState();
    const simSegments = [];
    const expansion = expandProgramLines(pattern.commands);
    if (!expansion.ok) {
        return simSegments;
    }

    for (let i = 0; i < expansion.lines.length; i += 1) {
        const source = expansion.lines[i];
        const parsed = parseCommand(source.text, source.lineNumber);
        if (parsed.skip || parsed.error) {
            continue;
        }
        const err = applyCommandToSimulation(simState, simSegments, parsed.command, parsed.args);
        if (err) {
            break;
        }
    }

    return simSegments;
}

async function moveToAnimated(endX, endY) {
    const startX = state.x;
    const startY = state.y;
    const dx = endX - startX;
    const dy = endY - startY;
    const distance = Math.hypot(dx, dy);
    const stepDistance = getAnimationStepDistance();
    const steps = Math.max(1, Math.ceil(distance / stepDistance));

    for (let i = 1; i <= steps; i += 1) {
        if (cancelRequested) {
            if (state.penDown && (state.x !== startX || state.y !== startY)) {
                segments.push({ x1: startX, y1: startY, x2: state.x, y2: state.y });
            }
            renderScene();
            return false;
        }

        const progress = i / steps;
        const currentX = startX + dx * progress;
        const currentY = startY + dy * progress;

        if (state.penDown) {
            renderScene({ x1: startX, y1: startY, x2: currentX, y2: currentY });
        } else {
            renderScene();
        }

        state.x = currentX;
        state.y = currentY;
        const wasCancelled = await sleepInterruptible(getFrameDelay());
        if (wasCancelled) {
            if (state.penDown && (state.x !== startX || state.y !== startY)) {
                segments.push({ x1: startX, y1: startY, x2: state.x, y2: state.y });
            }
            renderScene();
            return false;
        }
    }

    if (state.penDown) {
        segments.push({ x1: startX, y1: startY, x2: endX, y2: endY });
    }

    state.x = endX;
    state.y = endY;
    renderScene();
    return true;
}

async function executeUserCommand(command, args) {
    if (cancelRequested) {
        return "__CANCELLED__";
    }

    if (command === "forward") {
        const endX = state.x + args[0] * Math.cos(toRadians(state.angle));
        const endY = state.y + args[0] * Math.sin(toRadians(state.angle));
        const completed = await moveToAnimated(endX, endY);
        if (!completed) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "backward") {
        const endX = state.x - args[0] * Math.cos(toRadians(state.angle));
        const endY = state.y - args[0] * Math.sin(toRadians(state.angle));
        const completed = await moveToAnimated(endX, endY);
        if (!completed) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "left") {
        state.angle -= args[0];
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "right") {
        state.angle += args[0];
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "penup") {
        state.penDown = false;
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "pendown") {
        state.penDown = true;
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "goto") {
        const completed = await moveToAnimated(args[0], args[1]);
        if (!completed) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "setheading") {
        state.angle = args[0];
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    if (command === "home") {
        const initial = createInitialState();
        const completed = await moveToAnimated(initial.x, initial.y);
        if (!completed) {
            return "__CANCELLED__";
        }
        state.angle = initial.angle;
        renderScene();
        if (await sleepInterruptible(getCommandDelay())) {
            return "__CANCELLED__";
        }
        return null;
    }
    return "Neznamy nebo spatny format prikazu.";
}

function setButtonsDisabled(disabled) {
    drawBtn.disabled = disabled;
    clearBtn.disabled = disabled;
    if (stopBtn) {
        stopBtn.disabled = !disabled;
    }
    for (const btn of patternListEl.querySelectorAll("button")) {
        btn.disabled = disabled;
    }
}

function requestCancel() {
    if (!isRunning) {
        return;
    }
    cancelRequested = true;
    logEl.textContent = "Prerusuji vykreslovani...";
}

function setResult(evaluation) {
    const pct = Math.round(evaluation.score * 100);
    if (evaluation.isMatch) {
        resultEl.textContent = `Spravne (${pct} % shoda)`;
        resultEl.className = "result ok";
    } else {
        resultEl.textContent = `Nespravne (${pct} % shoda)`;
        resultEl.className = "result bad";
    }
}

async function loadProgress() {
    try {
        const response = await fetch("/api/progress");
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        for (const item of data.items || []) {
            progressByPattern.set(item.pattern_id, item);
            draftByPattern.set(item.pattern_id, typeof item.solution_text === "string" ? item.solution_text : "");
        }
        saveProgressCache();
        updateFooterStats();
    } catch (_) {
        // Ignore network issues and keep local-only mode.
    }
}

async function saveProgress(patternId, solutionText, solved, score) {
    const existing = progressByPattern.get(patternId);
    const wasSolved = Boolean(existing && existing.solved);
    const solvedEver = Boolean(solved) || Boolean(existing && existing.solved);
    const numericScore = Number(score) || 0;
    const prevScore = existing ? (Number(existing.score) || 0) : 0;
    const scoreToStore = solvedEver ? Math.max(prevScore, numericScore) : numericScore;

    if (!wasSolved && solvedEver && activePatternId === patternId && activePatternStartedAt) {
        flushActiveTaskTime(true);
    }

    const record = {
        pattern_id: patternId,
        solution_text: solutionText,
        solved: solvedEver,
        score: scoreToStore,
    };
    progressByPattern.set(patternId, record);
    setLocalDraft(patternId, solutionText);
    saveProgressCache();
    updateFooterStats();

    try {
        const response = await fetch(`/api/progress/${encodeURIComponent(patternId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                solution_text: solutionText,
                solved: solvedEver,
                score: scoreToStore,
            }),
        });
        if (response.ok) {
            const saved = await response.json();
            progressByPattern.set(patternId, saved);
            saveProgressCache();
            updateFooterStats();
        }
    } catch (_) {
        // Keep optimistic local state if backend temporarily unavailable.
    }
}

function getProgressState(patternId) {
    const existing = progressByPattern.get(patternId);
    if (!existing) {
        return { solved: false, score: 0 };
    }
    return {
        solved: Boolean(existing.solved),
        score: Number(existing.score) || 0,
    };
}

function persistDraft(patternId, solutionText, keepAlive = false) {
    if (!patternId) {
        return;
    }
    setLocalDraft(patternId, solutionText);

    const state = getProgressState(patternId);

    const record = {
        pattern_id: patternId,
        solution_text: solutionText,
        solved: state.solved,
        score: state.score,
    };
    progressByPattern.set(patternId, record);
    saveProgressCache();
    updateFooterStats();

    fetch(`/api/progress/${encodeURIComponent(patternId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            solution_text: solutionText,
            solved: state.solved,
            score: state.score,
        }),
        keepalive: keepAlive,
    })
        .then((response) => (response.ok ? response.json() : null))
        .then((saved) => {
            if (saved) {
                progressByPattern.set(patternId, saved);
                saveProgressCache();
                updateFooterStats();
            }
        })
        .catch(() => {
            // Keep optimistic local state if request fails.
        });
}

function persistCurrentDraft(keepAlive = false) {
    persistDraft(selectedPatternId, commandsEl.value, keepAlive);
}

function scheduleDraftSave() {
    if (isRunning || !selectedPatternId) {
        return;
    }

    const patternId = selectedPatternId;
    const snapshot = commandsEl.value;

    if (draftSaveTimer) {
        clearTimeout(draftSaveTimer);
    }

    draftSaveTimer = setTimeout(() => {
        draftSaveTimer = null;
        persistDraft(patternId, snapshot);
    }, 500);
}

function renderPatternMenu() {
    patternListEl.textContent = "";
    for (const category of CATEGORY_ORDER) {
        const categoryTitle = document.createElement("li");
        categoryTitle.className = "pattern-category";
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "pattern-category-toggle";
        const isCollapsed = collapsedCategories.has(category);
        toggle.textContent = `${isCollapsed ? "▸" : "▾"} ${category}`;
        toggle.addEventListener("click", () => {
            if (collapsedCategories.has(category)) {
                collapsedCategories.delete(category);
            } else {
                collapsedCategories.add(category);
            }
            renderPatternMenu();
        });
        categoryTitle.append(toggle);
        patternListEl.append(categoryTitle);

        if (isCollapsed) {
            continue;
        }

        const categoryPatterns = PATTERNS.filter((x) => x.category === category);
        for (const pattern of categoryPatterns) {
            const item = document.createElement("li");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "pattern-item";
            button.textContent = pattern.name;

            const progress = progressByPattern.get(pattern.id);
            if (progress && progress.solved) {
                button.classList.add("solved");
            }
            if (pattern.id === selectedPatternId) {
                button.classList.add("active");
            }
            if (hintUsedByPattern.get(pattern.id)) {
                const badge = document.createElement("span");
                badge.className = "hint-used-badge";
                badge.textContent = "N";
                badge.title = "Napoveda pouzita";
                button.append(badge);
            }

            const spentSeconds = getTaskElapsedSeconds(pattern.id);
            if (spentSeconds > 0) {
                const timeBadge = document.createElement("span");
                timeBadge.className = "pattern-time";
                timeBadge.textContent = formatDuration(spentSeconds);
                timeBadge.title = "Cas straveny na uloze";
                button.append(timeBadge);
            }

            button.addEventListener("click", () => {
                if (isRunning) {
                    return;
                }
                loadPattern(pattern.id);
            });

            item.append(button);
            patternListEl.append(item);
        }
    }
}

function loadPattern(patternId) {
    const previousPatternId = selectedPatternId;
    const previousText = commandsEl.value;
    if (!isRunning && previousPatternId && previousPatternId !== patternId && previousText) {
        if (draftSaveTimer) {
            clearTimeout(draftSaveTimer);
            draftSaveTimer = null;
        }
        persistDraft(previousPatternId, previousText);
    }

    const pattern = PATTERNS.find((x) => x.id === patternId) || PATTERNS[0];
    selectedPatternId = pattern.id;
    startTaskTimer(pattern.id);
    currentPatternEl.textContent = `Aktualni uloha: ${pattern.name}`;

    if (draftByPattern.has(pattern.id)) {
        commandsEl.value = draftByPattern.get(pattern.id) || "";
    } else {
    const saved = progressByPattern.get(pattern.id);
        if (saved && typeof saved.solution_text === "string") {
        commandsEl.value = saved.solution_text;
    } else {
        commandsEl.value = pattern.commands.slice(0, VISIBLE_SOLUTION_LINES).join("\n");
    }
    }

    if (pattern.hint) {
        patternHint.textContent = pattern.hint;
        patternHint.hidden = true;
        hintToggleBtn.hidden = false;
        hintToggleBtn.textContent = hintUsedByPattern.get(pattern.id)
            ? "Zobrazit napovedu (pouzita)"
            : "Zobraz napovedu";
    } else {
        patternHint.hidden = true;
        hintToggleBtn.hidden = true;
    }
    expectedSegments = buildExpectedSegments(pattern);
    resetCanvas();
    renderPatternMenu();
    updateFooterStats();
}

async function runCommands() {
    if (isRunning) {
        return;
    }

    isRunning = true;
    cancelRequested = false;
    setButtonsDisabled(true);
    resetCanvas();

    const expansion = expandProgramLines(commandsEl.value.split(/\r?\n/));
    if (!expansion.ok) {
        logEl.textContent = expansion.error;
        isRunning = false;
        setButtonsDisabled(false);
        return;
    }

    for (let i = 0; i < expansion.lines.length; i += 1) {
        const source = expansion.lines[i];
        const parsed = parseCommand(source.text, source.lineNumber);
        if (parsed.skip) {
            continue;
        }
        if (parsed.error) {
            logEl.textContent = parsed.error;
            isRunning = false;
            setButtonsDisabled(false);
            return;
        }

        const err = await executeUserCommand(parsed.command, parsed.args);
        if (err === "__CANCELLED__") {
            logEl.textContent = "Vykreslovani preruseno.";
            resultEl.textContent = "";
            resultEl.className = "result";
            isRunning = false;
            setButtonsDisabled(false);
            return;
        }
        if (err) {
            logEl.textContent = `${err} Na radku ${source.lineNumber}: ${parsed.raw}`;
            isRunning = false;
            setButtonsDisabled(false);
            return;
        }
    }

    const evaluation = evaluateDrawing();
    setResult(evaluation);
    logEl.textContent = `Hotovo. ${evaluation.reason}`;
    await saveProgress(selectedPatternId, commandsEl.value, evaluation.isMatch, evaluation.score);
    renderPatternMenu();

    isRunning = false;
    setButtonsDisabled(false);
}

drawBtn.addEventListener("click", runCommands);
clearBtn.addEventListener("click", resetCanvas);
if (stopBtn) {
    stopBtn.addEventListener("click", requestCancel);
}
if (hintToggleBtn) {
    hintToggleBtn.addEventListener("click", () => {
        const isHidden = patternHint.hidden;
        patternHint.hidden = !isHidden;
        hintToggleBtn.textContent = isHidden ? "Skryt napovedu (pouzita)" : "Zobrazit napovedu (pouzita)";
        if (isHidden && !hintUsedByPattern.get(selectedPatternId)) {
            saveHintUsage(selectedPatternId);
            renderPatternMenu();
        }
    });
}
commandsEl.addEventListener("keydown", handleEditorIndentation);
commandsEl.addEventListener("input", scheduleDraftSave);
window.addEventListener("beforeunload", () => {
    if (!isRunning) {
        persistCurrentDraft(true);
        flushActiveTaskTime(true);
    }
});
window.addEventListener("pagehide", () => {
    if (!isRunning) {
        persistCurrentDraft(true);
        flushActiveTaskTime(true);
    }
});
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        flushActiveTaskTime(true);
    } else if (activePatternId && !isRunning && !isPatternSolved(activePatternId)) {
        activePatternStartedAt = Date.now();
    }
});

async function initApp() {
    loadHintUsage();
    loadProgressCache();
    loadDraftStorage();
    loadTimeStorage();
    initSpeedControl();
    await loadProgress();
    renderPatternMenu();
    loadPattern(selectedPatternId);
    ensureFooterTicker();
    updateFooterStats();
}

initApp();
