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

from __future__ import annotations
from core import zyrox
from colorama import Fore, Style, init


from .commands.help import Help
from .commands.general import General
from .commands.music import Music
from .commands.automod import Automod
from .commands.welcome import Welcomer
from .commands.fun import Fun
from .commands.Games import Games
from .commands.extra import Extra
from .commands.owner import Owner
from .commands.voice import Voice
from .commands.afk import afk
from .commands.ignore import Ignore
from .commands.Media import Media
from .commands.Invc import Invcrole
from .commands.giveaway import Giveaway
from .commands.Embed import Embed
from .commands.steal import Steal
from .commands.timer import Timer
from .commands.blacklist import Blacklist
from .commands.block import Block
from .commands.nightmode import Nightmode
from .commands.tracking import Tracking
from .commands.owner import Badges
from .commands.autoresponder import AutoResponder
from .commands.customrole import Customrole
from .commands.autorole import AutoRole
from .commands.ticket import TicketCog
from .commands.logging import Logging
from .commands.translate import TranslateCog
from .commands.jail import Jail
from .commands.antinuke import Antinuke
from .commands.extraown import Extraowner
from .commands.anti_wl import Whitelist
from .commands.anti_unwl import Unwhitelist
from .commands.slots import Slots
from .commands.blackjack import Blackjack
from .commands.autoreact import AutoReaction
from .commands.stats import Stats
from .commands.emergency import Emergency
from .commands.notify import NotifCommands
from .commands.status import Status
from .commands.np import NoPrefix
from .commands.filters import FilterCog
from .commands.owner2 import Global
from .commands.qr import QR
from .commands.vanityroles import VanityRoles
from .commands.reactionroles import ReactionRoles 
from .commands.messages import Messages
from .commands.fastgreet import FastGreet
from .commands.counting import Counting
from .commands.j2c import JoinToCreate
from .commands.ai import AI 
from .commands.dms import StaffDMCog
from .commands.booster import Booster
from .commands.leveling import Leveling
from .commands.stickymessage import StickyMessage
from .commands.verification import Verification
from .commands.minecraft import Minecraft
from .commands.encryption import encryption
from .commands.calc import calculator
from .commands.joindm import joindm
from .commands.Birthday import Birthdays
from .commands.nitro import Nitro
from .commands.image import ImageCommands
from .commands.youtube import Youtube
from .commands.plans import Plans
#____________ Events _____________

from .events.Errors import Errors
from .events.on_guild import Guild
from .events.autorole import Autorole2
from .events.auto import Autorole
from .events.greet2 import greet
from .events.mention import Mention
from .events.react import React
from .events.autoreact import AutoReactListener
from .events.ai import AIResponses 
from .events.stickymessage import StickyMessageListener

########-------HELP-------########
from .zyrox.antinuke import _antinuke
from .zyrox.extra import _extra
from .zyrox.general import _general
from .zyrox.automod import _automod 
from .zyrox.moderation import _moderation
from .zyrox.music import _music
from .zyrox.fun import _fun
from .zyrox.games import _games
from .zyrox.ignore import _ignore
from .zyrox.server import _server
from .zyrox.voice import _voice 
from .zyrox.welcome import _welcome 
from .zyrox.giveaway import _giveaway
from .zyrox.ticket import _ticket
from .zyrox.logging import _logging
from .zyrox.vanity import _vanity
from .zyrox.inviteTracker import inviteTracker 
from .zyrox.counting import _Counting
from .zyrox.j2c import _J2C
from .zyrox.ai import _ai
from .zyrox.booster import __boost 
from .zyrox.leveling import _leveling
from .zyrox.sticky import _sticky
from .zyrox.verify import _verify
from .zyrox.encryption import _encrypt
from .zyrox.mc import _mc
from .zyrox.joindm import _joindm
from .zyrox.birth import _birth

#########ANTINUKE#########

from .antinuke.anti_member_update import AntiMemberUpdate
from .antinuke.antiban import AntiBan
from .antinuke.antibotadd import AntiBotAdd
from .antinuke.antichcr import AntiChannelCreate
from .antinuke.antichdl import AntiChannelDelete
from .antinuke.antichup import AntiChannelUpdate
from .antinuke.antieveryone import AntiEveryone
from .antinuke.antiguild import AntiGuildUpdate
from .antinuke.antiIntegration import AntiIntegration
from .antinuke.antikick import AntiKick
from .antinuke.antiprune import AntiPrune
from .antinuke.antirlcr import AntiRoleCreate
from .antinuke.antirldl import AntiRoleDelete
from .antinuke.antirlup import AntiRoleUpdate
from .antinuke.antiwebhook import AntiWebhookUpdate
from .antinuke.antiwebhookcr import AntiWebhookCreate
from .antinuke.antiwebhookdl import AntiWebhookDelete

#Extra Optional Events 

#from .antinuke.antiemocr import AntiEmojiCreate
#from .antinuke.antiemodl import AntiEmojiDelete
#from .antinuke.antiemoup import AntiEmojiUpdate
#from .antinuke.antisticker import AntiSticker
#from .antinuke.antiunban import AntiUnban

############ AUTOMOD ############
from .automod.antispam import AntiSpam
from .automod.anticaps import AntiCaps
from .automod.antilink import AntiLink
from .automod.anti_invites import AntiInvite
from .automod.anti_mass_mention import AntiMassMention
from .automod.anti_emoji_spam import AntiEmojiSpam


from .moderation.ban import Ban
from .moderation.unban import Unban
from .moderation.timeout import Mute
from .moderation.unmute import Unmute
from .moderation.lock import Lock
from .moderation.unlock import Unlock
from .moderation.hide import Hide
from .moderation.unhide import Unhide
from .moderation.kick import Kick
from .moderation.warn import Warn
from .moderation.role import Role
from .moderation.message import Message
from .moderation.moderation import Moderation
from .moderation.topcheck import TopCheck
from .moderation.snipe import Snipe


from utils.config import BotName

async def setup(bot: zyrox):
  loaded = 0
  failed = []

  async def _safe_add(cog_type):
    # A single broken or optional cog must never take the whole bot down:
    # log it clearly and keep loading the rest.
    nonlocal loaded
    try:
      await bot.add_cog(cog_type(bot))
      loaded += 1
    except Exception as exc:
      failed.append(cog_type.__name__)
      print(Fore.RED + Style.BRIGHT + f"Failed to load cog {cog_type.__name__}: {exc}", flush=True)


  await _safe_add(Help)
  await _safe_add(General)
  await _safe_add(Music)
  await _safe_add(Automod)
  await _safe_add(Welcomer)
  await _safe_add(Fun)
  await _safe_add(Tracking)
  await _safe_add(Games)
  await _safe_add(Extra)
  await _safe_add(Voice)
  await _safe_add(Owner)
  await _safe_add(Customrole)
  await _safe_add(afk)
  await _safe_add(Embed)
  await _safe_add(Media)
  await _safe_add(Ignore)
  await _safe_add(Invcrole)
  await _safe_add(Giveaway)
  await _safe_add(Steal)
  await _safe_add(Booster)
  await _safe_add(Timer)
  await _safe_add(Blacklist)
  await _safe_add(Block)
  await _safe_add(Nightmode)
  await _safe_add(Badges)
  await _safe_add(Antinuke)
  await _safe_add(Whitelist)
  await _safe_add(Unwhitelist)
  await _safe_add(Extraowner)
  await _safe_add(Slots)
  await _safe_add(Blackjack)
  await _safe_add(Stats)
  await _safe_add(Emergency)
  await _safe_add(Status)
  await _safe_add(NoPrefix)
  await _safe_add(FilterCog)
  await _safe_add(Global)
  await _safe_add(TicketCog)
  await _safe_add(Logging)
  await _safe_add(QR)
  await _safe_add(VanityRoles)
  await _safe_add(ReactionRoles)
  await _safe_add(Messages)
  await _safe_add(TranslateCog)
  await _safe_add(FastGreet)
  await _safe_add(Jail)
  await _safe_add(JoinToCreate)
  await _safe_add(AI)
  await _safe_add(StaffDMCog)
  await _safe_add(Leveling)
  await _safe_add(StickyMessage)
  await _safe_add(Verification)
  await _safe_add(Minecraft)
  await _safe_add(encryption)
  await _safe_add(calculator)
  await _safe_add(joindm)
  await _safe_add(Birthdays)
  await _safe_add(Nitro)
  await _safe_add(ImageCommands)
  await _safe_add(Youtube)
  await _safe_add(Plans)

  await _safe_add(_antinuke)
  await _safe_add(_extra)
  await _safe_add(_general)
  await _safe_add(_automod)
  await _safe_add(_moderation)
  await _safe_add(_music)
  await _safe_add(_fun)
  await _safe_add(_games)
  await _safe_add(_ignore)
  await _safe_add(_server)
  await _safe_add(_voice)
  await _safe_add(_welcome)
  await _safe_add(_giveaway)
  await _safe_add(_ticket)
  await _safe_add(_logging)
  await _safe_add(_vanity)
  await _safe_add(inviteTracker)
  await _safe_add(Counting)
  await _safe_add(_Counting)
  await _safe_add(_J2C)
  await _safe_add(_ai)
  await _safe_add(__boost)
  await _safe_add(_leveling)
  await _safe_add(_sticky)
  await _safe_add(_verify)
  await _safe_add(_encrypt)
  await _safe_add(_mc)
  await _safe_add(_joindm)
  await _safe_add(_birth)

  await _safe_add(Guild)
  await _safe_add(Errors)
  await _safe_add(Autorole2)
  await _safe_add(Autorole)
  await _safe_add(greet)
  await _safe_add(AutoResponder)
  await _safe_add(Mention)
  await _safe_add(AutoRole)
  await _safe_add(React)
  await _safe_add(AutoReaction)
  await _safe_add(AutoReactListener)
  await _safe_add(NotifCommands)
  await _safe_add(StickyMessageListener)
  await _safe_add(AIResponses)


  await _safe_add(AntiMemberUpdate)
  await _safe_add(AntiBan)
  await _safe_add(AntiBotAdd)
  await _safe_add(AntiChannelCreate)
  await _safe_add(AntiChannelDelete)
  await _safe_add(AntiChannelUpdate)
  await _safe_add(AntiEveryone)
  await _safe_add(AntiGuildUpdate)
  await _safe_add(AntiIntegration)
  await _safe_add(AntiKick)
  await _safe_add(AntiPrune)
  await _safe_add(AntiRoleCreate)
  await _safe_add(AntiRoleDelete)
  await _safe_add(AntiRoleUpdate)
  await _safe_add(AntiWebhookUpdate)
  await _safe_add(AntiWebhookCreate)
  await _safe_add(AntiWebhookDelete)

  await _safe_add(AntiSpam)
  await _safe_add(AntiCaps)
  await _safe_add(AntiInvite)
  await _safe_add(AntiLink)
  await _safe_add(AntiMassMention)
  await _safe_add(AntiEmojiSpam)







  await _safe_add(Ban)
  await _safe_add(Unban)
  await _safe_add(Mute)
  await _safe_add(Unmute)
  await _safe_add(Lock)
  await _safe_add(Unlock)
  await _safe_add(Hide)
  await _safe_add(Unhide)
  await _safe_add(Kick)
  await _safe_add(Warn)
  await _safe_add(Role)
  await _safe_add(Message)
  await _safe_add(Moderation)
  await _safe_add(TopCheck)
  await _safe_add(Snipe)
  


  if loaded == 0:
    raise RuntimeError(f"no cogs could be loaded: {', '.join(failed) or 'unknown error'}")

  print(Fore.GREEN + Style.BRIGHT + f"Loaded {loaded} cogs for {BotName}.")
  if failed:
    print(Fore.YELLOW + Style.BRIGHT + f"WARNING - {len(failed)} cog(s) failed to load: {', '.join(failed)}")
  else:
    print(Fore.GREEN + Style.BRIGHT + f"All {BotName} Cogs loaded successfully.")
