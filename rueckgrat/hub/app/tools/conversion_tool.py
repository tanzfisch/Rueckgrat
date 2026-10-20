from typing import Dict, Any, Optional, Tuple
import math
import re
import threading
import time
import requests
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

# ---------------------------------------------------------------------------------------------------------------------
# 1) STATIC UNITS: fixed physical conversions, baked into the code, never looked up on the network.
#
#    every unit is converted into the SI base unit of its dimension with an affine formula:
#        base_value = value * factor + offset
#    offset is 0 for everything except temperatures (C, F) whose zero point differs from kelvin.
#    to add a unit: add a line to its dimension. to add a dimension: add a new dict entry.
#    format: canonical name -> (factor, offset, [aliases]). aliases are matched case-insensitive.
# ---------------------------------------------------------------------------------------------------------------------
TROY_OUNCE_KG = 0.0311034768

STATIC_UNITS: Dict[str, Dict[str, Tuple[float, float, list]]] = {
    "length": {  # base: metre
        "m":   (1.0, 0, ["meter", "meters", "metre", "metres"]),
        "km":  (1000.0, 0, ["kilometer", "kilometers", "kilometre", "kilometres"]),
        "cm":  (0.01, 0, ["centimeter", "centimeters", "centimetre", "centimetres"]),
        "mm":  (0.001, 0, ["millimeter", "millimeters", "millimetre", "millimetres"]),
        "um":  (1e-6, 0, ["µm", "micrometer", "micrometers", "micrometre", "micrometres", "micron", "microns"]),
        "nm":  (1e-9, 0, ["nanometer", "nanometers", "nanometre", "nanometres"]),
        "in":  (0.0254, 0, ["inch", "inches", "\""]),
        "ft":  (0.3048, 0, ["foot", "feet", "'"]),
        "yd":  (0.9144, 0, ["yard", "yards"]),
        "mi":  (1609.344, 0, ["mile", "miles"]),
        "nmi": (1852.0, 0, ["nautical mile", "nautical miles"]),
        "ly":  (9.4607304725808e15, 0, ["light year", "light years", "lightyear", "lightyears"]),
        "au":  (149597870700.0, 0, ["astronomical unit", "astronomical units"]),
    },
    "mass": {  # base: kilogram
        "kg":  (1.0, 0, ["kilogram", "kilograms", "kilo", "kilos"]),
        "g":   (0.001, 0, ["gram", "grams", "gramme", "grammes"]),
        "mg":  (1e-6, 0, ["milligram", "milligrams"]),
        "t":   (1000.0, 0, ["tonne", "tonnes", "metric ton", "metric tons"]),
        "lb":  (0.45359237, 0, ["lbs", "pound", "pounds"]),
        "oz":  (0.028349523125, 0, ["ounce", "ounces"]),  # avoirdupois ounce (food, body weight)
        "ozt": (TROY_OUNCE_KG, 0, ["troy oz", "troy ounce", "troy ounces", "oz t"]),  # precious metals
        "st":  (6.35029318, 0, ["stone", "stones"]),
        "short ton": (907.18474, 0, ["us ton", "us tons", "short tons"]),
        "long ton":  (1016.0469088, 0, ["uk ton", "uk tons", "long tons", "imperial ton"]),
        "ct":  (0.0002, 0, ["carat", "carats"]),
    },
    "volume": {  # base: cubic metre
        "m3":  (1.0, 0, ["m³", "cubic meter", "cubic meters", "cubic metre", "cubic metres"]),
        "l":   (0.001, 0, ["liter", "liters", "litre", "litres"]),
        "ml":  (1e-6, 0, ["milliliter", "milliliters", "millilitre", "millilitres", "cm3", "cm³", "cc"]),
        "cl":  (1e-5, 0, ["centiliter", "centiliters", "centilitre", "centilitres"]),
        "dl":  (1e-4, 0, ["deciliter", "deciliters", "decilitre", "decilitres"]),
        "gal": (0.003785411784, 0, ["gallon", "gallons", "us gal", "us gallon", "us gallons"]),  # US gallon
        "imp gal": (0.00454609, 0, ["uk gal", "uk gallon", "uk gallons", "imperial gallon", "imperial gallons"]),
        "qt":  (0.000946352946, 0, ["quart", "quarts", "us quart"]),
        "pt":  (0.000473176473, 0, ["pint", "pints", "us pint", "us pints"]),
        "imp pt": (0.00056826125, 0, ["uk pint", "uk pints", "imperial pint", "imperial pints"]),
        "cup": (0.0002365882365, 0, ["cups", "us cup"]),
        "fl oz": (2.95735295625e-5, 0, ["floz", "fluid ounce", "fluid ounces", "us fl oz"]),
        "tbsp": (1.478676478125e-5, 0, ["tablespoon", "tablespoons"]),
        "tsp": (4.92892159375e-6, 0, ["teaspoon", "teaspoons"]),
        "ft3": (0.028316846592, 0, ["ft³", "cubic foot", "cubic feet"]),
        "in3": (1.6387064e-5, 0, ["in³", "cubic inch", "cubic inches"]),
    },
    "area": {  # base: square metre
        "m2":  (1.0, 0, ["m²", "sqm", "square meter", "square meters", "square metre", "square metres"]),
        "km2": (1e6, 0, ["km²", "square kilometer", "square kilometers", "square kilometre", "square kilometres"]),
        "cm2": (1e-4, 0, ["cm²", "square centimeter", "square centimeters", "square centimetre", "square centimetres"]),
        "ha":  (1e4, 0, ["hectare", "hectares"]),
        "acre": (4046.8564224, 0, ["acres", "ac"]),
        "ft2": (0.09290304, 0, ["ft²", "sqft", "sq ft", "square foot", "square feet"]),
        "in2": (0.00064516, 0, ["in²", "sq in", "square inch", "square inches"]),
        "mi2": (2589988.110336, 0, ["mi²", "sq mi", "square mile", "square miles"]),
    },
    "temperature": {  # base: kelvin. the only dimension that needs an offset
        "K":   (1.0, 0, ["kelvin", "kelvins"]),
        "°C":  (1.0, 273.15, ["c", "degc", "celsius", "centigrade", "degree celsius", "degrees celsius"]),
        "°F":  (5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0, ["f", "degf", "fahrenheit", "degree fahrenheit", "degrees fahrenheit"]),
        "°R":  (5.0 / 9.0, 0, ["rankine"]),
    },
    "speed": {  # base: metre per second
        "m/s":  (1.0, 0, ["mps", "meter per second", "meters per second", "metre per second", "metres per second"]),
        "km/h": (1000.0 / 3600.0, 0, ["kmh", "kph", "kmph", "kilometer per hour", "kilometers per hour", "kilometre per hour", "kilometres per hour"]),
        "mph":  (1609.344 / 3600.0, 0, ["mi/h", "mile per hour", "miles per hour"]),
        "kn":   (1852.0 / 3600.0, 0, ["kt", "knot", "knots"]),
        "ft/s": (0.3048, 0, ["fps", "foot per second", "feet per second"]),
        "c":    (299792458.0, 0, ["speed of light"]),
    },
    "time": {  # base: second
        "s":   (1.0, 0, ["sec", "secs", "second", "seconds"]),
        "ms":  (0.001, 0, ["millisecond", "milliseconds"]),
        "us":  (1e-6, 0, ["µs", "microsecond", "microseconds"]),
        "ns":  (1e-9, 0, ["nanosecond", "nanoseconds"]),
        "min": (60.0, 0, ["mins", "minute", "minutes"]),
        "h":   (3600.0, 0, ["hr", "hrs", "hour", "hours"]),
        "d":   (86400.0, 0, ["day", "days"]),
        "wk":  (604800.0, 0, ["week", "weeks"]),
        "mo":  (2629746.0, 0, ["month", "months"]),        # average Gregorian month (365.2425 / 12 days)
        "yr":  (31556952.0, 0, ["year", "years", "a"]),    # average Gregorian year (365.2425 days)
    },
    # data sizes, base: byte. decimal SI prefixes (KB = 1000 B, like disk vendors and the IEC standard),
    # binary IEC prefixes (KiB = 1024 B, like RAM and most OS file browsers) are separate units.
    "data": {
        "B":   (1.0, 0, ["byte", "bytes"]),
        "bit": (0.125, 0, ["bits"]),
        "KB":  (1e3, 0, ["kilobyte", "kilobytes", "kb"]),
        "MB":  (1e6, 0, ["megabyte", "megabytes", "mb"]),
        "GB":  (1e9, 0, ["gigabyte", "gigabytes", "gb"]),
        "TB":  (1e12, 0, ["terabyte", "terabytes", "tb"]),
        "PB":  (1e15, 0, ["petabyte", "petabytes", "pb"]),
        "KiB": (1024.0, 0, ["kibibyte", "kibibytes", "kib"]),
        "MiB": (1024.0 ** 2, 0, ["mebibyte", "mebibytes", "mib"]),
        "GiB": (1024.0 ** 3, 0, ["gibibyte", "gibibytes", "gib"]),
        "TiB": (1024.0 ** 4, 0, ["tebibyte", "tebibytes", "tib"]),
        "kbit": (125.0, 0, ["kilobit", "kilobits"]),
        "Mbit": (125000.0, 0, ["megabit", "megabits"]),
        "Gbit": (1.25e8, 0, ["gigabit", "gigabits"]),
    },
    "energy": {  # base: joule
        "J":    (1.0, 0, ["joule", "joules"]),
        "kJ":   (1e3, 0, ["kilojoule", "kilojoules"]),
        "MJ":   (1e6, 0, ["megajoule", "megajoules"]),
        "cal":  (4.184, 0, ["calorie", "calories"]),
        "kcal": (4184.0, 0, ["kilocalorie", "kilocalories", "food calorie", "food calories"]),
        "Wh":   (3600.0, 0, ["watt hour", "watt hours"]),
        "kWh":  (3.6e6, 0, ["kilowatt hour", "kilowatt hours"]),
        "BTU":  (1055.05585262, 0, ["btus", "british thermal unit"]),
        "eV":   (1.602176634e-19, 0, ["electronvolt", "electronvolts"]),
    },
    "power": {  # base: watt
        "W":   (1.0, 0, ["watt", "watts"]),
        "kW":  (1e3, 0, ["kilowatt", "kilowatts"]),
        "MW":  (1e6, 0, ["megawatt", "megawatts"]),
        "hp":  (745.69987158227, 0, ["horsepower", "bhp"]),  # mechanical horsepower
        "PS":  (735.49875, 0, ["metric horsepower", "ps"]),
    },
    "pressure": {  # base: pascal
        "Pa":  (1.0, 0, ["pascal", "pascals"]),
        "hPa": (100.0, 0, ["hectopascal", "hectopascals"]),
        "kPa": (1000.0, 0, ["kilopascal", "kilopascals"]),
        "bar": (1e5, 0, ["bars"]),
        "mbar": (100.0, 0, ["millibar", "millibars"]),
        "psi": (6894.757293168, 0, ["pound per square inch", "pounds per square inch"]),
        "atm": (101325.0, 0, ["atmosphere", "atmospheres"]),
        "mmHg": (133.322387415, 0, ["torr", "millimeter of mercury"]),
    },
}

# alias -> (dimension, canonical, factor, offset), built once at import time
_UNIT_INDEX: Dict[str, Tuple[str, str, float, float]] = {}
for _dim, _units in STATIC_UNITS.items():
    for _name, (_factor, _offset, _aliases) in _units.items():
        for _alias in [_name] + _aliases:
            _UNIT_INDEX.setdefault(_alias.lower(), (_dim, _name, _factor, _offset))

# ---------------------------------------------------------------------------------------------------------------------
# 2) LIVE RATES: currency exchange rates and precious metal prices, the only values fetched from the network.
#    source: fawazahmed0/exchange-api, free, no API key, ~340 currencies incl. metals (XAU, XAG, XPT, XPD) and crypto,
#    updated daily. metal codes are priced per troy ounce (1 XAU = 1 troy ounce of gold).
# ---------------------------------------------------------------------------------------------------------------------
LIVE_RATE_URLS = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{code}.min.json",
    "https://latest.currency-api.pages.dev/v1/currencies/{code}.min.json",  # fallback mirror
]
LIVE_RATE_TIMEOUT = 10        # seconds per request
LIVE_RATE_CACHE_SECONDS = 3600

METALS = {
    "xau": ["gold"],
    "xag": ["silver"],
    "xpt": ["platinum"],
    "xpd": ["palladium"],
}
CURRENCY_ALIASES = {
    "usd": ["$", "us$", "dollar", "dollars", "us dollar", "us dollars", "american dollar", "american dollars"],
    "eur": ["€", "euro", "euros"],
    "gbp": ["£", "pound sterling", "british pound", "british pounds", "sterling", "quid"],
    "jpy": ["¥", "yen", "japanese yen"],
    "nzd": ["nz$", "nz dollar", "nz dollars", "new zealand dollar", "new zealand dollars", "kiwi dollar"],
    "aud": ["a$", "au$", "australian dollar", "australian dollars", "aussie dollar"],
    "cad": ["c$", "canadian dollar", "canadian dollars"],
    "chf": ["swiss franc", "swiss francs", "franc", "francs"],
    "cny": ["yuan", "renminbi", "rmb", "chinese yuan"],
    "inr": ["₹", "rupee", "rupees", "indian rupee", "indian rupees"],
    "sek": ["swedish krona", "swedish kronor"],
    "nok": ["norwegian krone", "norwegian kroner"],
    "dkk": ["danish krone", "danish kroner"],
    "rub": ["ruble", "rubles", "rouble", "roubles"],
    "krw": ["won", "korean won"],
    "mxn": ["mexican peso", "mexican pesos"],
    "brl": ["real", "reais", "brazilian real"],
    "btc": ["₿", "bitcoin", "bitcoins"],
    "eth": ["ether", "ethereum"],
}
_CURRENCY_INDEX: Dict[str, str] = {}
for _code, _aliases in CURRENCY_ALIASES.items():
    for _alias in _aliases:
        _CURRENCY_INDEX[_alias] = _code
_METAL_INDEX: Dict[str, str] = {}
for _code, _aliases in METALS.items():
    for _alias in [_code] + _aliases:
        _METAL_INDEX[_alias] = _code


class ConversionError(Exception):
    """a user facing problem (unknown unit, mismatch, no rate), its message goes back to the LLM"""


class LiveRateProvider:
    """fetches and caches the rate table of one base currency. shared by all tool instances (class level cache)"""
    _cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    _lock = threading.Lock()

    @classmethod
    def get_table(cls, code: str) -> Dict[str, Any]:
        """returns {"date": "YYYY-MM-DD", "rates": {code: rate}} where rate = units of code per 1 base"""
        with cls._lock:
            cached = cls._cache.get(code)
            if cached and time.time() - cached[0] < LIVE_RATE_CACHE_SECONDS:
                return cached[1]

        last_error = None
        for url in LIVE_RATE_URLS:
            try:
                resp = requests.get(url.format(code=code), timeout=LIVE_RATE_TIMEOUT)
                if resp.status_code == 404:
                    raise ConversionError(f"unknown unit or currency '{code.upper()}'")
                resp.raise_for_status()
                data = resp.json()
                table = {"date": data.get("date", "unknown"), "rates": data[code]}
                with cls._lock:
                    cls._cache[code] = (time.time(), table)
                return table
            except ConversionError:
                raise
            except Exception as e:
                logger.warning(f"live rate fetch failed {url.format(code=code)} {repr(e)}")
                last_error = e
        raise ConversionError(f"exchange rate service unreachable ({type(last_error).__name__})")

    @classmethod
    def rate(cls, from_code: str, to_code: str) -> Tuple[float, str]:
        """units of to_code per 1 from_code, plus the rate date"""
        if from_code == to_code:
            return 1.0, "n/a"
        table = cls.get_table(from_code)
        rate = table["rates"].get(to_code)
        if rate is None:
            raise ConversionError(f"unknown unit or currency '{to_code.upper()}'")
        return float(rate), table["date"]


def _normalize(text: str) -> str:
    text = str(text).strip().lower().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"^(of |per |a |an |one )", "", text)


def _resolve_static(text: str) -> Optional[Dict[str, Any]]:
    key = _normalize(text)
    hit = _UNIT_INDEX.get(key)
    if hit is None and key.endswith("s"):
        hit = _UNIT_INDEX.get(key[:-1])  # cheap plural fallback ("kgs", "gals")
    if hit is None:
        return None
    dim, name, factor, offset = hit
    return {"kind": "static", "dimension": dim, "unit": name, "factor": factor, "offset": offset}


def _resolve_live(text: str) -> Optional[Dict[str, Any]]:
    """currency ('usd', 'euro', '$') or metal with optional mass ('gold', 'oz gold', '10 g of gold', 'kg silver').
    result: code plus multiplier = how many units of that code one unit of the text is (1 g gold = 0.032 XAU)"""
    key = _normalize(text)
    if key in _CURRENCY_INDEX:
        code = _CURRENCY_INDEX[key]
        return {"kind": "live", "code": code, "multiplier": 1.0, "unit": code.upper()}

    words = key.replace(" of ", " ").split(" ")
    metal = next((w for w in words if w in _METAL_INDEX), None)
    if metal:
        code = _METAL_INDEX[metal]
        mass_text = " ".join(w for w in words if w != metal and w not in ("per", "of", "a", "one"))
        if mass_text in ("", "oz", "ounce", "ounces"):
            mass_text = "ozt"  # precious metals are always traded in troy ounces
        mass = _resolve_static(mass_text)
        if not mass or mass["dimension"] != "mass":
            raise ConversionError(f"'{text}': '{mass_text}' is not a mass unit")
        multiplier = mass["factor"] / TROY_OUNCE_KG
        return {"kind": "live", "code": code, "multiplier": multiplier, "unit": f"{'troy oz' if mass['unit'] == 'ozt' else mass['unit']} {METALS[code][0]}"}

    if re.fullmatch(r"[a-z0-9]{2,10}", key):
        # looks like a currency code, the rate service validates it
        return {"kind": "live", "code": key, "multiplier": 1.0, "unit": key.upper()}
    return None


# the resolvers in order: static units win, so "cup" is a volume and not the Cuban peso.
# to add a new category, write a resolver returning {"kind": ...} and a matching branch in convert()
RESOLVERS = [_resolve_static, _resolve_live]


def _resolve(text: str) -> Dict[str, Any]:
    for resolver in RESOLVERS:
        hit = resolver(text)
        if hit:
            return hit
    raise ConversionError(f"unknown unit or currency '{text}'")


def _format(value: float) -> str:
    if value == 0:
        return "0"
    if not math.isfinite(value):
        return str(value)
    decimals = max(2, 5 - int(math.floor(math.log10(abs(value)))))
    text = f"{value:,.{min(decimals, 12)}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def convert(amount: Any, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """core conversion, no side effects. raises ConversionError for user facing problems"""
    try:
        value = float(str(amount).replace(",", "").replace("_", "").strip())
    except ValueError:
        raise ConversionError(f"invalid amount '{amount}'")

    src = _resolve(from_unit)
    dst = _resolve(to_unit)

    if src["kind"] == "static" and dst["kind"] == "static":
        if src["dimension"] != dst["dimension"]:
            raise ConversionError(f"cannot convert {src['dimension']} ({src['unit']}) into {dst['dimension']} ({dst['unit']})")
        base = value * src["factor"] + src["offset"]
        result = (base - dst["offset"]) / dst["factor"]
        return {
            "amount": value, "from": src["unit"], "to": dst["unit"], "result": result,
            "text": f"{_format(value)} {src['unit']} = {_format(result)} {dst['unit']}",
            "category": src["dimension"], "source": "static conversion table",
        }

    if src["kind"] == "live" and dst["kind"] == "live":
        rate, date = LiveRateProvider.rate(src["code"], dst["code"])
        result = value * src["multiplier"] * rate / dst["multiplier"]
        unit_rate = src["multiplier"] * rate / dst["multiplier"]
        return {
            "amount": value, "from": src["unit"], "to": dst["unit"], "result": result,
            "rate": unit_rate,
            "text": f"{_format(value)} {src['unit']} = {_format(result)} {dst['unit']} (1 {src['unit']} = {_format(unit_rate)} {dst['unit']})",
            "category": "currency", "date": date, "source": "fawazahmed0 exchange-api (daily rates)",
        }

    static, live = (src, dst) if src["kind"] == "static" else (dst, src)
    raise ConversionError(f"cannot mix {static['dimension']} ({static['unit']}) with '{live['unit']}', it is not a {static['dimension']} unit")


class ConversionTool(Tool):
    category = ToolCategory.MATH
    description = "converts amounts between currencies, crypto and physical units, prices gold/silver/platinum in any currency"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "convert"

    def execute(self) -> None:
        if not all(k in self.tool_call for k in ("amount", "from", "to")):
            logger.error("invalid convert")
            return None

        amount = self.tool_call["amount"]
        from_unit = self.tool_call["from"]
        to_unit = self.tool_call["to"]
        MessageQueue().send_status_message("converting")

        try:
            result = convert(amount, from_unit, to_unit)
            logger.debug(f"convert: {result['text']}")
        except ConversionError as e:
            logger.warning(f"convert {amount} {from_unit} -> {to_unit} failed: {e}")
            result = {"amount": amount, "from": from_unit, "to": to_unit, "error": str(e)}
        except Exception as e:
            logger.error(f"failed to convert {repr(e)}")
            result = {"amount": amount, "from": from_unit, "to": to_unit, "error": "conversion failed"}

        # a list, the LLM may convert several things in one answer
        self.response.setdefault("conversion_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
CONVERT:

Use the convert tool for any conversion of an amount from one unit into another: currencies and crypto (live daily exchange rates), prices of gold, silver, platinum and palladium in any currency (per troy ounce, gram, kg, ...), and physical units (length, mass, volume, area, temperature, speed, time, data sizes, energy, power, pressure). Prefer it over websearch for exchange rates and metal prices. One call per conversion:
{
  "tool": "convert",
  "amount": 100,
  "from": "USD",
  "to": "EUR"
}
Examples for "from"/"to": "USD", "euro", "NZD", "BTC", "oz gold", "g gold", "kg silver", "km", "miles", "lb", "°C", "°F", "l", "gal", "GB", "MB", "kWh", "psi"
"""
