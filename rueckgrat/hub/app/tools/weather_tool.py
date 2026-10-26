from typing import Dict,  Any
import requests
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

# open-meteo, free, no key: geocoding (place name -> coordinates) plus forecast
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_TIMEOUT = 10
FORECAST_DAYS = 3

# WMO weather interpretation codes, as used by open-meteo
WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers", 85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}


class WeatherError(Exception):
    pass


def get_weather(location: str) -> str:
    try:
        resp = requests.get(GEOCODING_URL, params={"name": location, "count": 1, "language": "en", "format": "json"}, timeout=WEATHER_TIMEOUT)
        resp.raise_for_status()
        places = resp.json().get("results") or []
        if not places:
            raise WeatherError(f"unknown location '{location}'")
        place = places[0]

        resp = requests.get(FORECAST_URL, params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": FORECAST_DAYS,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        }, timeout=WEATHER_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except WeatherError:
        raise
    except Exception as e:
        logger.warning(f"weather request failed {repr(e)}")
        raise WeatherError(f"weather service unreachable ({type(e).__name__})")

    name = ", ".join(p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p)
    cur = data["current"]
    text = (f"weather in {name} at {cur['time'].replace('T', ' ')} local time: "
            f"{WEATHER_CODES.get(cur['weather_code'], 'unknown')}, {cur['temperature_2m']} °C (feels like {cur['apparent_temperature']} °C), "
            f"humidity {cur['relative_humidity_2m']} %, wind {cur['wind_speed_10m']} km/h. Forecast:")
    daily = data["daily"]
    for i, day in enumerate(daily["time"]):
        rain = daily["precipitation_probability_max"][i]
        text += (f" {day}: {WEATHER_CODES.get(daily['weather_code'][i], 'unknown')}, "
                 f"{daily['temperature_2m_min'][i]} to {daily['temperature_2m_max'][i]} °C"
                 f"{f', {rain} % chance of rain' if rain is not None else ''};")
    return text.rstrip(";") + " - source open-meteo.com"


class WeatherTool(Tool):
    category = ToolCategory.WEB
    description = "current weather and 3 day forecast for a place"
    question = "Does the user want to know about the weather?"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "weather"

    def execute(self) -> None:
        if not "location" in self.tool_call:
            logger.error("invalid weather")
            return None

        location = self.tool_call["location"]
        MessageQueue().send_status_message("checking the weather")

        try:
            result = {"tool": self.name(), "text": get_weather(location)}
        except WeatherError as e:
            logger.warning(f"weather {location} failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to get weather {repr(e)}")
            result = {"tool": self.name(), "error": "weather lookup failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
WEATHER:
Use for current weather and 3-day forecast. Prefer this over websearch for weather.

Parameters:
- location (string, required): city or place name

Example:
{"tool": "weather", "location": "Auckland"}
"""
