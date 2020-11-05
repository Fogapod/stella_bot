import discord
import datetime
import re
import asyncio
import itertools
import ctypes

import humanize
from discord.ext import commands
from discord.ext.commands import BucketType, MemberNotFound, UserNotFound
from discord.ext.menus import ListPageSource, MenuPages
from utils.new_converters import BotPrefix, BotUsage, IsBot
from utils.useful import try_call, BaseEmbed, compile_prefix, search_prefix, MenuBase
from utils.errors import NotInDatabase, BotNotFound
from utils.decorators import is_discordpy


class BotAdded:
    def __init__(self, *, author=None, bot=None, reason=None, requested_at=None, jump_url=None, joined_at=None):
        self.author = author
        self.bot = bot
        self.reason = reason
        self.requested_at = requested_at
        self.jump_url = jump_url
        self.joined_at = joined_at

    @classmethod
    def to_add(cls, member, data=None):
        author = data["author_id"]
        reason = data['reason']
        jump_url = data['jump_url']
        requested_at = data['requested_at']

        bot = member
        author = member.guild.get_member(author)
        return cls(author=author, bot=bot, reason=reason, requested_at=requested_at, jump_url=jump_url,
                   joined_at=bot.joined_at)

    @classmethod
    def from_json(cls, data, bot=None):
        author = data["author_id"]
        reason = data['reason']
        jump_url = data['jump_url']
        requested_at = data['requested_at']
        join = None
        if bot and isinstance(bot, discord.Member):
            join = bot.joined_at
            author = bot.guild.get_member(author)
        elif 'joined_at' in data:
            join = data['joined_at']

        return cls(author=author, bot=bot, reason=reason, requested_at=requested_at, jump_url=jump_url, joined_at=join)

    @classmethod
    async def convert(cls, ctx, argument):
        instance = commands.MemberConverter()

        async def create_botdata(user, table):
            data = await ctx.bot.pg_con.fetchrow(f"SELECT * FROM {table} WHERE bot_id = $1", user.id)
            return cls.from_json(data, user)

        if member := await try_call(instance.convert(ctx, argument), MemberNotFound):
            if member.id not in ctx.bot.confirmed_bots and member.id not in ctx.bot.pending_bots:
                raise NotInDatabase(member.id)

            if member.id in ctx.bot.confirmed_bots:
                return await create_botdata(member, "confirmed_bots")
        else:
            if user := await try_call(ctx.bot.fetch_user(int(argument)), discord.NotFound):
                if user.id in ctx.bot.confirmed_bots:
                    return await create_botdata(member, "confirmed_bots")
                if user.id in ctx.bot.pending_bots:
                    return await create_botdata(member, "pending_bots")
        raise BotNotFound(argument)

    def __repr__(self):
        return '<author = {0.author},' \
               ' bot = {0.bot},' \
               ' reason = "{0.reason}",' \
               ' requested_at = {0.requested_at},' \
               ' jump_url = "{0.jump_url}",' \
               ' joined_at = {0.joined_at}>'.format(self)


class AllPrefixes(ListPageSource):
    def __init__(self, data):
        super().__init__(data, per_page=6)

    async def format_page(self, menu: MenuPages, entries):
        key = "(\u200b|\u200b)"
        offset = menu.current_page * self.per_page

        async def pprefix(prefix):
            if re.search("<@(!?)([0-9]*)>", prefix):
                try:
                    user = await commands.UserConverter().convert(menu.ctx, re.sub(" ", "", prefix))
                    return f"@{user.display_name}"
                except:
                    pass
            return prefix

        contents = [f'`{i + 1}. {k} {key} {await pprefix(p)}`' for i, (k, p) in enumerate(entries, start=offset)]
        high = max(cont.index(key) for cont in contents)
        reform = [high - cont.index(key) for cont in contents]
        true_form = [x.replace(key, f'{" " * off} |') for x, off in zip(contents, reform)]
        embed = BaseEmbed(description="\n".join(true_form))
        return embed


class FindBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        valid_prefix = ("!", "?", "？", "<@(!?)80528701850124288> ")
        re_command = "(\{}|\{}|\{}|({}))addbot".format(*valid_prefix)
        re_bot = "[\s|\n]+(?P<id>[0-9]{17,19})[\s|\n]"
        re_reason = "+(?P<reason>.[\s\S\r]+)"
        self.re_addbot = re_command + re_bot + re_reason
        self.compiled_pref = None
        self.all_bot_prefixes = None
        bot.loop.create_task(self.loading_all_prefixes())

    async def loading_all_prefixes(self):
        await self.bot.wait_until_ready()
        datas = await self.bot.pg_con.fetch("SELECT * FROM bot_prefix")
        self.all_bot_prefixes = {data["bot_id"]: data["prefix"] for data in datas}
        temp = list(set(self.all_bot_prefixes.values()))
        self.compiled_pref = compile_prefix(sorted(temp))

    DPY_ID = 336642139381301249

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id == self.DPY_ID and member.bot:
            if member.id in self.bot.pending_bots:
                data = await self.bot.pg_con.fetchrow("SELECT * FROM pending_bots WHERE bot_id = $1", member.id)
                await self.update_confirm(BotAdded.from_json(data, member))
                await self.bot.pg_con.execute("DELETE FROM pending_bots WHERE bot_id = $1", member.id)
            else:
                data = {"author_id": None,
                        "reason": None,
                        "requested_at": None,
                        "jump_url": None,
                        "joined_at": member.joined_at
                        }
                await self.update_confirm(BotAdded.from_json(data, member))

    async def update_prefix_bot(self, message, func, prefix):
        def setting(inner):
            def check(msg):
                if msg.channel != message.channel:
                    return False
                if not msg.author.bot:
                    return True
                return inner(msg)

            return check

        bots = []
        while message.created_at + datetime.timedelta(seconds=2) > datetime.datetime.utcnow():
            waiting = try_call(self.bot.wait_for, asyncio.TimeoutError, args=("message",),
                               kwargs={"check": setting(func), "timeout": 1})
            if m := await waiting:
                if not m.author.bot:
                    break
                if not (m.author.id in self.all_bot_prefixes and self.all_bot_prefixes[m.author.id] == prefix):
                    bots.append(m.author.id)
        if not bots:
            return
        query = "INSERT INTO bot_prefix VALUES($1, $2) ON CONFLICT (bot_id) DO UPDATE SET prefix=$2"
        values = [(x, prefix) for x in bots]

        await self.bot.pg_con.executemany(query, values)
        self.all_bot_prefixes.update({x: prefix for x, prefix in values})
        temp = list(set(self.all_bot_prefixes.values()))
        self.compiled_pref = compile_prefix(sorted(temp))

    @commands.Cog.listener(name="on_message")
    async def find_bot_prefix(self, message):
        if message.author.bot:
            return
        if match := re.match("(?P<prefix>^.{1,30}?(?=jsk$))", message.content):
            def check(m):
                possible_text = ("Jishaku", "discord.py", "Python ", "Module ", "guild(s)", "user(s).")
                return all(f"{x}" in m.content.lower() for x in possible_text)

            await self.update_prefix_bot(message, check, match["prefix"])
            return

        if match := re.match("(?P<prefix>^.{1,30}?(?=help$))", message.content):
            def check(m):
                def search(search_text):
                    possible_text = ("command", "help", "category", "categories")
                    return any(f"{x}" in search_text.lower() for x in possible_text)

                content = search(m.content)
                embeds = any(search(str(x.to_dict())) for x in m.embeds)
                return content or embeds

            await self.update_prefix_bot(message, check, match["prefix"])

    @commands.Cog.listener("on_message")
    async def command_count(self, message):
        if not self.compiled_pref:
            return
        limit = len(message.content) if len(message.content) < 31 else 31
        content_compiled = ctypes.create_string_buffer(message.content[:limit].encode("utf-8"))
        result = search_prefix(self.compiled_pref, content_compiled)
        if not result:
            return

        bots = await self.bot.pg_con.fetch("SELECT * FROM bot_prefix WHERE prefix=$1", result)
        match_bot = {bot["bot_id"] for bot in bots if message.guild.get_member(bot["bot_id"])}

        def check(msg):
            return msg.author.bot and msg.channel == message.channel and msg.author.id in match_bot

        bot_found = []
        while message.created_at + datetime.timedelta(seconds=5) > datetime.datetime.utcnow():
            waiting = try_call(self.bot.wait_for, asyncio.TimeoutError, args=("message",),
                               kwargs={"check": check, "timeout": 1})
            if m := await waiting:
                bot_found.append(m.author.id)
            if len(bot_found) == len(match_bot):
                break
        if not bot_found:
            return
        query = "INSERT INTO bot_usage_count VALUES($1, $2) ON CONFLICT (bot_id) DO UPDATE SET count=bot_usage_count.count + 1"
        values = [(x, 1) for x in bot_found]

        await self.bot.pg_con.executemany(query, values)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id not in (559455534965850142, 381963689470984203, 381963705686032394):
            return
        if message.author.bot:
            return
        if result := await self.is_valid_addbot(message, check=True):
            confirm = False

            def terms_acceptance(msg):
                nonlocal confirm
                if msg.author.id != message.author.id:
                    return False
                if msg.channel.id != message.channel.id:
                    return False
                if msg.content in ('**I agree**', 'I agree'):
                    confirm = True
                    return True
                elif msg.content in ('**Abort**', 'Abort'):
                    return True
                return False

            try:
                await self.bot.wait_for("message", check=terms_acceptance, timeout=60)
            except asyncio.TimeoutError:
                return

            if not confirm:
                return
            await self.update_pending(result)

    async def check_author(self, bot_id, author_id, mode):
        if data := await self.bot.pg_con.fetchrow(f"SELECT * FROM {mode} WHERE bot_id=$1", bot_id):
            old_author = data['author_id']
            return old_author == author_id

    async def is_valid_addbot(self, message, check=False):
        if result := re.match(self.re_addbot, message.content):
            reason = result["reason"]
            get_member = message.guild.get_member
            if not check:
                member = get_member(int(result["id"]))
                six_days = datetime.datetime.utcnow() - datetime.timedelta(days=6)
                if not member and message.created_at > six_days:
                    member = await try_call(self.bot.fetch_user(int(result["id"])), discord.NotFound)
                    if all((reason, member and member.bot and str(member.id) not in self.bot.pending_bots)):
                        if str(member.id) not in self.bot.confirmed_bots:
                            await self.update_pending(
                                BotAdded(author=message.author,
                                         bot=member,
                                         reason=reason,
                                         requested_at=message.created_at,
                                         jump_url=message.jump_url))
                        return

            else:
                if member := get_member(int(result["id"])):
                    print("This bot", int(result["id"]), "is already in the guild.")
                    if int(result["id"]) not in self.bot.confirmed_bots and \
                            await self.check_author(member.id, message.author.id, "confirmed_bots"):
                        newAddBot = BotAdded(author=message.author,
                                             bot=member,
                                             reason=reason,
                                             requested_at=message.created_at,
                                             jump_url=message.jump_url,
                                             joined_at=member.joined_at)
                        await self.update_confirm(newAddBot)
                    return
                member = await try_call(self.bot.fetch_user(int(result["id"])), discord.NotFound)
            if all((reason, member and member.bot)):
                join = None
                if isinstance(member, discord.Member):
                    join = member.joined_at
                    if join < message.created_at:
                        return
                return BotAdded(author=message.author,
                                bot=member,
                                reason=reason,
                                requested_at=message.created_at,
                                jump_url=message.jump_url,
                                joined_at=join)

    async def update_pending(self, result):
        query = """INSERT INTO pending_bots VALUES($1, $2, $3, $4, $5) 
                   ON CONFLICT (bot_id) DO
                   UPDATE SET reason = $3, requested_at=$4, jump_url=$5"""
        value = (result.bot.id, result.author.id, result.reason, result.requested_at, result.jump_url)
        await self.bot.pg_con.execute(query, *value)
        if result.bot.id not in self.bot.pending_bots:
            self.bot.pending_bots.add(result.bot.id)

    async def update_confirm(self, result):
        query = """INSERT INTO confirmed_bots VALUES($1, $2, $3, $4, $5, $6) 
                   ON CONFLICT (bot_id) DO
                   UPDATE SET reason = $3, requested_at=$4, jump_url=$5, joined_at=$6"""
        if not result.author:
            return self.bot.pending_bots.remove(result.bot.id)

        value = (result.bot.id, result.author.id, result.reason, result.requested_at, result.jump_url, result.joined_at)
        await self.bot.pg_con.execute(query, *value)
        if result.bot.id in self.bot.pending_bots:
            self.bot.pending_bots.remove(result.bot.id)
        if result.bot.id not in self.bot.confirmed_bots:
            self.bot.confirmed_bots.add(result.bot.id)

    @commands.command(help="Shows what bot has the user owns in discord.py.",
                      aliases=["owns", "userowns", "whatadds", "whatadded"])
    @is_discordpy()
    @commands.cooldown(1, 5, BucketType.user)
    async def whatadd(self, ctx, author: discord.Member = None):
        if not author:
            author = ctx.author
        if author.bot:
            return await ctx.send("That's a bot lol")
        query = "SELECT * FROM {}_bots WHERE author_id=$1"
        total_list = [await self.bot.pg_con.fetch(query.format(x), author.id) for x in ("pending", "confirmed")]
        total_list = list(itertools.chain.from_iterable(total_list))
        list_bots = [ctx.guild.get_member(x["bot_id"]) or x["bot_id"] for x in total_list]
        embed = discord.Embed(title=f"{author}'s Bots", color=self.bot.color)
        embed.set_thumbnail(url=author.avatar_url)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar_url)
        embed.add_field(name="Bots Owned:",
                        value=", ".join(str(x) for x in list_bots) or f"{author} doesnt own any bot here.")
        await ctx.send(embed=embed)

    @commands.command(aliases=["whoowns", "whosebot", "whoadds", "whoadded"], help="Shows who added the bot.")
    @is_discordpy()
    @commands.cooldown(1, 5, BucketType.user)
    async def whoadd(self, ctx, bot: BotAdded):
        data = bot
        author = await try_call(commands.UserConverter().convert(ctx, str(data.author)), UserNotFound)
        embed = discord.Embed(title=f"{data.bot}",
                              color=self.bot.color)
        request = data.requested_at.strftime("%d %b %Y %I:%M %p %Z") if data.requested_at else None
        join = data.joined_at.strftime("%d %b %Y %I:%M %p %Z") if data.joined_at else None
        embed.set_thumbnail(url=data.bot.avatar_url)
        fields = (("Reason", data.reason),
                  ("Requested", request),
                  ("Joined", join),
                  ("Message Request", f"[jump]({data.jump_url})" if data.jump_url else None))

        if author:
            embed.set_author(name=author, icon_url=author.avatar_url)
        for name, value in fields:
            if value:
                embed.add_field(name=name, value=value, inline=False)

        await ctx.send(embed=embed)

    @commands.group(invoke_without_command=True, hidden=True)
    async def who(self, ctx):
        pass

    @who.command(hidden=True, aliases=["added", "adds"])
    @is_discordpy(silent=True)
    @commands.cooldown(1, 10, BucketType.user)
    async def add(self, ctx, data: BotAdded):
        await ctx.invoke(self.whoadd, data)

    @commands.command(aliases=["wp"], help="Shows the prefix of a bot")
    @commands.guild_only()
    async def whatprefix(self, ctx, member: BotPrefix):
        embed = BaseEmbed.default(ctx,
                                  title=f"{member}'s Prefix",
                                  description=f"`{member.prefix}`")

        await ctx.send(embed=embed)

    @commands.command(aliases=["pc", "shares", "pconflict"],
                      help="Shows the number of conflict(shares) a prefix have between bots.")
    @commands.guild_only()
    async def prefixconflict(self, ctx, prefix):
        instance_bot = await self.get_all_prefix(ctx.guild, prefix)
        conflict = (0, len(instance_bot))[len(instance_bot) > 1]
        await ctx.send(
            embed=BaseEmbed.default(ctx, description=f"There are `{conflict}` conflict(s) with `{prefix}` prefix"))

    async def get_all_prefix(self, guild, prefix):
        data = await self.bot.pg_con.fetch("SELECT * FROM bot_prefix WHERE prefix=$1", prefix)

        def mem(x):
            return guild.get_member(x)

        return [mem(x['bot_id']) for x in data if mem(x['bot_id'])]

    @commands.command(aliases=["pb", "prefixbots", "pbots"],
                      help="Shows which bot(s) have a given prefix.")
    @commands.guild_only()
    async def prefixbot(self, ctx, prefix):
        instance_bot = await self.get_all_prefix(ctx.guild, prefix)
        list_bot = "\n".join(f"{no + 1}. {x}" for no, x in enumerate(instance_bot)) or "`Not a single bot have it.`"
        await ctx.send(embed=BaseEmbed.default(ctx,
                                               description=f"Bot{('s', '')[len(list_bot) < 2]} with `{prefix}` as prefix\n"
                                                           f"{list_bot}"))

    @commands.command(aliases=["ap", "aprefix", "allprefixes"],
                      help="Shows every bot's prefix in the server.")
    @commands.guild_only()
    async def allprefix(self, ctx):
        bots = await self.bot.pg_con.fetch("SELECT * FROM bot_prefix")

        def mem(x):
            return ctx.guild.get_member(x)

        members = [(mem(bot["bot_id"]), bot["prefix"]) for bot in bots if mem(bot["bot_id"])]
        menu = MenuBase(source=AllPrefixes(members), delete_message_after=True)
        await menu.start(ctx)

    @commands.command(aliases=["bot_use", "bu", "botusage", "botuses"],
                      help="Show's how many command calls for the bot.")
    async def botuse(self, ctx, bot: BotUsage):
        embed = BaseEmbed.default(ctx,
                                  title=f"{bot}'s Usage",
                                  description=f"The bot has been used for `{bot.count}` times.")

        await ctx.send(embed=embed)

    @commands.command(aliases=["bot_info", "bi", "botinfos"])
    async def botinfo(self, ctx, bot: IsBot):
        # TODO: this is pretty terrible, optimise this
        titles = (("Bot Prefix", "{0.prefix}", BotPrefix),
                  ("Command Usage", "{0.count}", BotUsage),
                  (("Bot Invited by", "{0.author}"),
                   (("Reason", "reason"),
                    ("Requested at", 'requested_at')),
                   BotAdded))
        embed = BaseEmbed.default(ctx, title=str(bot))
        embed.set_thumbnail(url=bot.avatar_url)
        embed.add_field(name="ID", value=f"`{bot.id}`")
        for title, attrib, converter in reversed(titles):
            if obj := await try_call(converter.convert, Exception, args=(ctx, str(bot.id))):
                if isinstance(attrib, tuple):
                    for t, a in attrib:
                        if dat := getattr(obj, a):
                            dat = dat if not isinstance(dat, datetime.datetime) else dat.strftime("%d %b %Y %I:%M %p %Z")
                            embed.add_field(name=t, value=f"`{dat}`", inline=False)

                    title, attrib = title
                embed.add_field(name=title, value=f"`{attrib.format(obj)}`", inline=False)

        embed.add_field(name="Created at", value=f"`{bot.created_at.strftime('%d %b %Y %I:%M %p %Z')}`")
        embed.add_field(name="Joined at", value=f"`{bot.joined_at.strftime('%d %b %Y %I:%M %p %Z')}`")
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(FindBot(bot))
