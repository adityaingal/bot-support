# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import discord
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, MediaGallery
import random
import asyncio
import aiohttp
from discord import app_commands
from utils.Tools import blacklist_check, ignore_check
from utils.cv2 import CV2, build_container

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.giphy_api_key = "y3KcqQTdiS0RYcpNJrWn8hFGglKqX4is"

    async def fetch_giphy(self, query):
        # Request gzip only: brotli responses raise ClientPayloadError with the
        # installed Brotli package, which killed every fun command.
        headers = {"Accept-Encoding": "gzip, deflate"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"https://api.giphy.com/v1/gifs/search"
                    f"?api_key={self.giphy_api_key}&q={query}&limit=30&rating=pg"
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if data['data']:
                        return random.choice(data['data'])['images']['original']['url']
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            return None

    async def _json_get(self, url, params=None):
        headers = {"Accept-Encoding": "gzip, deflate"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=12)
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None

    def random_emoji(self):
        return random.choice(["😂", "🤣", "😆", "😳", "🥴", "🙃", "😜"])

    async def action_command(self, ctx, user: discord.Member, action: str):
        gif_url = await self.fetch_giphy(action)
        if not gif_url:
            await ctx.send(view=CV2("😒 Error", "GIPHY API is sleeping. Try later!"))
            return
        view = LayoutView(timeout=None)
        gallery = MediaGallery()
        gallery.add_item(media=gif_url)
        view.add_item(build_container(
            TextDisplay(f"**{ctx.author.mention} {action}s {user.mention} {self.random_emoji()}**"),
            gallery
        ))
        await ctx.send(view=view)

    async def meter_command(self, ctx, title, user, text):
        await ctx.send(view=CV2(title, text))

    @commands.command(name="shipp")
    @blacklist_check()
    @ignore_check()
    async def shipp(self, ctx, user1: discord.Member, user2: discord.Member):
        percentage = random.randint(0, 100)
        await ctx.send(view=CV2(f"{self.random_emoji()} Ship Result", f"**{user1.mention} x {user2.mention} = {percentage}% Love**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def hug(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "hug")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def kiss(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "kiss")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def pat(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "pat")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def slap(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "slap")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def tickle(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "tickle")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def coinflip(self, ctx):
        result = random.choice(["Heads", "Tails"])
        await ctx.send(view=CV2("🪙 Coin Flip", f"**Result: {result}**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def dice(self, ctx):
        result = random.randint(1, 6)
        await ctx.send(view=CV2("🎲 Dice Roll", f"**You rolled a {result}!**"))

    @commands.command(name="8ball")
    @blacklist_check()
    @ignore_check()
    async def eight_ball(self, ctx, *, question: str):
        responses = ["It is certain.", "Without a doubt.", "You may rely on it.",
                     "Ask again later.", "Better not tell you now.",
                     "Don't count on it.", "My sources say no.", "Very doubtful."]
        await ctx.send(view=CV2("🎱 Magic 8Ball", f"**Q:** {question}\n**A:** {random.choice(responses)}"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def roast(self, ctx, user: discord.Member):
        roasts = [
            f"{user.mention} you're the reason shampoo has instructions!",
            f"{user.mention} you have something on your chin... no, the third one down!",
            f"{user.mention} your secrets are safe with me. I never even listen when you tell me them."
        ]
        await ctx.send(view=CV2("🔥 Roast Time", random.choice(roasts)))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def iq(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🧠 IQ Test", f"**{user.mention} has an IQ of {random.randint(50, 200)}!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def dumb(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🤪 Dumbness Test", f"**{user.mention} is {random.randint(0, 100)}% dumb!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def simprate(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("😳 Simp Rate", f"**{user.mention} is {random.randint(0, 100)}% simp!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def toxic(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("☠️ Toxic Meter", f"**{user.mention} is {random.randint(0, 100)}% toxic!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def intelligence(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🧠 Intelligence Meter", f"**{user.mention} has {random.randint(0, 200)} IQ Points!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def genius(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🤓 Genius Rate", f"**{user.mention} is {random.randint(0, 100)}% genius!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def brainrate(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🧠 Brain Power", f"**{user.mention} is using {random.randint(0, 100)}% of their brain!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def howhot(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🔥 Hotness Meter", f"**{user.mention} is {random.randint(0, 100)}% hot!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def spank(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "spank")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def cuddle(self, ctx, user: discord.Member):
        await self.action_command(ctx, user, "cuddle")

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def ship(self, ctx, user1: discord.Member, user2: discord.Member = None):
        if user2 is None:
            pool = [
                m for m in ctx.guild.members
                if m.id not in (ctx.author.id, user1.id) and not m.bot
            ]
            if not pool:
                await ctx.send(view=CV2("😒 Error", "There's nobody else here to ship you with!"))
                return
            user2 = random.choice(pool)
        percentage = random.randint(0, 100)
        await ctx.send(view=CV2(
            f"{self.random_emoji()} Ship Result",
            f"**{user1.mention} x {user2.mention} = {percentage}% Love**"
        ))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def lesbian(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🌈 Lesbian Meter", f"**{user.mention} is {random.randint(0, 100)}% lesbian!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def cute(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🥰 Cuteness Meter", f"**{user.mention} is {random.randint(0, 100)}% cute!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def tharki(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("😏 Tharki Meter", f"**{user.mention} is {random.randint(0, 100)}% tharki!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def chutiya(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🤡 Chutiya Meter", f"**{user.mention} is {random.randint(0, 100)}% chutiya!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def howgay(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("🌈 Gay Meter", f"**{user.mention} is {random.randint(0, 100)}% gay!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def horny(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await ctx.send(view=CV2("😈 Horny Meter", f"**{user.mention} is {random.randint(0, 100)}% horny!**"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def gif(self, ctx, *, query: str = "funny"):
        gif_url = await self.fetch_giphy(query)
        if not gif_url:
            await ctx.send(view=CV2("😒 Error", "GIPHY API is sleeping. Try later!"))
            return
        view = LayoutView(timeout=None)
        gallery = MediaGallery()
        gallery.add_item(media=gif_url)
        view.add_item(build_container(TextDisplay(f"**GIF for:** {query}"), gallery))
        await ctx.send(view=view)

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def truth(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        questions = [
            "What's the most embarrassing thing on your phone right now?",
            "What's a lie you've told recently?",
            "Who was your first crush?",
            "What's the weirdest thing you've ever eaten?",
            "What's your biggest fear?",
            "What's the last thing you searched for on your phone?",
            "Have you ever broken something and blamed someone else?",
            "What's a secret talent nobody here knows about?",
        ]
        await ctx.send(view=CV2("🫢 Truth", f"**{user.mention},** {random.choice(questions)}"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def dare(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        dares = [
            "Change your nickname to 'I Lost A Dare' for 1 hour.",
            "Send a message with only emojis describing your day.",
            "Type your last sent message in all caps here.",
            "Compliment the person above you in chat.",
            "Post a selfie with a funny face.",
            "Let the person above you pick your status for 30 minutes.",
            "Use only one word replies for the next 5 messages.",
            "Say something nice about someone you don't talk to much.",
        ]
        await ctx.send(view=CV2("😈 Dare", f"**{user.mention},** {random.choice(dares)}"))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def mydog(self, ctx):
        data = await self._json_get("https://dog.ceo/api/breeds/image/random")
        if not data or data.get("status") != "success":
            await ctx.send(view=CV2("😒 Error", "Dog API is sleeping. Try later!"))
            return
        view = LayoutView(timeout=None)
        gallery = MediaGallery()
        gallery.add_item(media=data["message"])
        view.add_item(build_container(TextDisplay("**🐕 Have a random dog!**"), gallery))
        await ctx.send(view=view)

    WEATHER_CODES = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        56: "Light freezing drizzle", 57: "Dense freezing drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        66: "Light freezing rain", 67: "Heavy freezing rain",
        71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
        77: "Snow grains",
        80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
        85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
    }

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def weather(self, ctx, *, city: str):
        geo = await self._json_get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": city, "count": 1, "language": "en", "format": "json"},
        )
        if not geo or not geo.get("results"):
            await ctx.send(view=CV2("😒 Weather Error", f"**No location found for** `{city}`"))
            return
        place = geo["results"][0]
        fc = await self._json_get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                           "precipitation,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
        )
        if not fc or "current" not in fc:
            await ctx.send(view=CV2("😒 Weather Error", "Weather service is unreachable right now. Try again!"))
            return
        cur = fc["current"]
        desc = self.WEATHER_CODES.get(cur.get("weather_code"), "Unknown conditions")
        location = f"{place.get('name')}, {place.get('country')}"
        text = (
            f"**{desc}**\n"
            f"🌡️ Temperature: **{cur.get('temperature_2m')}°C** "
            f"(feels like {cur.get('apparent_temperature')}°C)\n"
            f"💧 Humidity: **{cur.get('relative_humidity_2m')}%**\n"
            f"🌧️ Precipitation: {cur.get('precipitation')} mm\n"
            f"💨 Wind: {cur.get('wind_speed_10m')} km/h\n"
            f"🕐 Local time: {cur.get('time', 'N/A')}"
        )
        await ctx.send(view=CV2(f"⛅ Weather · {location}", text))

    @commands.command()
    @blacklist_check()
    @ignore_check()
    async def iplookup(self, ctx, ip: str):
        data = await self._json_get(f"https://ipwho.is/{ip.strip()}")
        if not isinstance(data, dict) or not data.get("success", True):
            reason = data.get("message", "Invalid IP address") if isinstance(data, dict) else "Invalid IP address"
            await ctx.send(view=CV2("😒 IP Lookup Error", f"**{reason}**"))
            return
        conn = data.get("connection", {})
        tz = data.get("timezone", {})
        country = data.get("country", "Unknown")
        if data.get("country_code"):
            country = f"{country} ({data.get('country_code')})"
        text = (
            f"🌍 **{country}**\n"
            f"🏙️ Region: {data.get('region', 'Unknown')}\n"
            f"📍 City: {data.get('city', 'Unknown')}\n"
            f"📮 Postal: {data.get('postal', 'N/A')}\n"
            f"🌐 Type: {data.get('type', 'N/A')}\n"
            f"🏢 ISP: {conn.get('isp', 'N/A')}\n"
            f"🧬 ASN: {conn.get('asn', 'N/A')}\n"
            f"🕒 Timezone: {tz.get('id', 'N/A')}"
        )
        await ctx.send(view=CV2(f"🌐 IP Lookup · {data.get('ip', ip)}", text))

async def setup(bot):
    await bot.add_cog(Fun(bot))