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
import asyncio
import aiohttp
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, Container
from utils.cv2 import CV2, build_container

class TranslateSuccess(LayoutView):
    def __init__(self, original, translated, author):
        super().__init__(timeout=None)
        self.add_item(
            build_container(
                TextDisplay("🌐 **Translation Complete**"),
                Separator(visible=True),
                TextDisplay(f"**Original (Hinglish):**\n{original}"),
                Separator(visible=True),
                TextDisplay(f"**Translated (English):**\n{translated}"),
                Separator(visible=True),
                TextDisplay(f"Requested by **{author.display_name}**")
            )
        )

class TranslateError(LayoutView):
    def __init__(self, error_msg):
        super().__init__(timeout=None)
        self.add_item(
            build_container(
                TextDisplay("❌ **Translation Failed**"),
                Separator(visible=True),
                TextDisplay(f"`{error_msg}`")
            )
        )

class TranslateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def translate_text(self, text: str) -> str:
        # deep-translator is blocking (and capped at ~5 req/s) — run it in a
        # worker thread and back off before retrying when Google throttles.
        # Imported here: deep_translator drags in bs4/soupsieve (~230ms) that
        # boot would otherwise pay for every restart.
        from deep_translator import GoogleTranslator
        last_error = None
        for delay in (0.0, 2.0, 4.0):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await asyncio.to_thread(
                    GoogleTranslator(source="auto", target="en").translate, text
                )
            except Exception as exc:
                last_error = exc

        # Fallback 1: Google's keyless gtx endpoint (separate quota pool).
        try:
            headers = {"Accept-Encoding": "gzip, deflate"}
            params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        result = "".join(
                            seg[0] for seg in data[0] if isinstance(seg, (list, tuple)) and seg
                        )
                        if result:
                            return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError):
            pass

        # Fallback 2: MyMemory (free, no key, no Google quota).
        try:
            headers = {"Accept-Encoding": "gzip, deflate"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    "https://api.mymemory.translated.net/get",
                    params={"q": text[:500], "langpair": "hi|en"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        translated = (data.get("responseData") or {}).get("translatedText")
                        if translated and translated != text:
                            return translated
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            pass

        message = str(last_error or "")
        if "too many requests" in message.lower():
            raise Exception(
                "Google is rate-limiting this IP (5 req/s, 200k per day). "
                "Wait about a minute and try again."
            )
        raise last_error if last_error else Exception("Translation failed. Try again later.")

    @commands.hybrid_command(
        name="hinglish",
        help="Translate informal Hinglish to proper English.",
        usage="!hinglish chlo udhr chat active krlo idhr nai"
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def hinglish(self, ctx: commands.Context, *, text: str = None):
        if not text:
            return await ctx.reply(
                "⚠️ Please provide some Hinglish text to translate.",
                ephemeral=True if ctx.interaction else False
            )

        msg = await ctx.reply(
            "🔄 Translating Hinglish...",
            ephemeral=True if ctx.interaction else False
        )

        try:
            translated = await self.translate_text(text)

            view = TranslateSuccess(text, translated, ctx.author)
            await msg.edit(content=None, view=view, embed=None)

        except Exception as e:
            view = TranslateError(str(e) or "Google is throttling requests. Wait a moment and try again.")
            await msg.edit(content=None, view=view, embed=None)

async def setup(bot):
    await bot.add_cog(TranslateCog(bot))
