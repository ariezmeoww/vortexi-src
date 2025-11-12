import discord
import requests
import logging
import time
from discord import app_commands
from config import Config
config = Config()
nowidthspace = "\u200b" # https://unicode-explorer.com/c/200B for more info on this character
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def FormatBackendUrl(Endpoint: str) -> str:
    """
    Formats the given endpoint into a full URL to the Vortexi backend server.
    """
    return f"{config.BackendServerUrl}/internal/discord_bot/{Endpoint}"

async def GetRequestSession() -> requests.Session:
    """
    Returns a requests session with the proper headers set.
    """
    RequestSession = requests.Session()
    RequestSession.headers.update({
        "InternalAuthorizationKey": config.BackendAuthenticationToken,
        "Content-Type": "application/json",
        "User-Agent": "SyntaxBot/1.0"
    })
    return RequestSession

async def BuildUserEmbed( UserObject: dict ) -> discord.Embed:
    UserEmbed = discord.Embed()
    UserEmbed.title = UserObject["username"]
    UserEmbed.description = nowidthspace.join(UserObject["description"]) + nowidthspace
    UserEmbed.color = discord.Color.green()
    UserEmbed.url = f"https://www.vortexi.cc/users/{UserObject['id']}/profile"
    UserEmbed.set_thumbnail(url=f"https://www.vortexi.cc/Thumbs/Head.ashx?x=100&y=100&userId={UserObject['id']}")
    UserEmbed.add_field(name="UserId", value=UserObject["id"])
    UserEmbed.add_field(name="Created at", value=f"<t:{int(UserObject['created_at'])}:f>")
    UserEmbed.add_field(name="Last online", value=f"<t:{int(UserObject['last_online'])}:f>")
    UserEmbed.add_field(name="Membership", value=UserObject["membership"])

    return UserEmbed

async def BuildItemEmbed( ItemObject: dict ) -> discord.Embed:
    ItemEmbed = discord.Embed()
    ItemEmbed.title = ItemObject["name"]
    ItemEmbed.description = nowidthspace.join(ItemObject["description"]) + nowidthspace
    ItemEmbed.color = discord.Color.green()
    ItemEmbed.url = f"https://www.vortexi.cc/catalog/{ItemObject['id']}/"
    ItemEmbed.set_thumbnail(url=f"https://www.vortexi.cc/Thumbs/Asset.ashx?x=180&y=180&assetId={ItemObject['id']}")
    ItemEmbed.add_field(name="ItemId", value=ItemObject["id"])
    ItemEmbed.add_field(name="Created at", value=f"<t:{int(ItemObject['created_at'])}:f>")
    ItemEmbed.add_field(name="Updated at", value=f"<t:{int(ItemObject['updated_at'])}:f>")
    if ItemObject["creator"] != None:
        ItemEmbed.add_field(name="Creator", value=f"[{ItemObject['creator']['username']}](https://www.vortexi.cc/users/{ItemObject['creator']['id']}/profile)")
    else:
        ItemEmbed.add_field(name="Creator", value="Group")
    if ItemObject["is_for_sale"]:
        # If "price_robux" and "price_tickets" are both 0, then the item is free.
        # If "price_robux" is 0, then the item is only for sale with tickets.
        # If "price_tickets" is 0, then the item is only for sale with robux.
        # If neither are 0, then the item is for sale with both.
        if ItemObject["price_robux"] == 0 and ItemObject["price_tickets"] == 0:
            ItemEmbed.add_field(name="Price", value="Free")
        elif ItemObject["price_robux"] == 0 and ItemObject["price_tickets"] != 0:
            ItemEmbed.add_field(name="Price", value=f"{ItemObject['price_tickets']} Tickets")
        elif ItemObject["price_robux"] != 0 and ItemObject["price_tickets"] == 0:
            ItemEmbed.add_field(name="Price", value=f"{ItemObject['price_robux']} Robux")
        else:
            ItemEmbed.add_field(name="Price", value=f"{ItemObject['price_robux']} Robux or {ItemObject['price_tickets']} Tickets")

    if ItemObject["is_limited"]:
        if ItemObject["is_limited_unique"]:
            ItemEmbed.add_field(name="Limited", value="Yes (Unique)")
        else:
            ItemEmbed.add_field(name="Limited", value="Yes")

    if ItemObject["asset_rap"] != None:
        ItemEmbed.add_field(name="RAP", value=ItemObject["asset_rap"])

    ItemEmbed.add_field(name="Sales", value=ItemObject["sales"])
    ItemEmbed.add_field(name="Asset Type", value=ItemObject["asset_type"])

    return ItemEmbed

class DiscordBot( discord.Client ):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    
    async def setup_hook(self) -> None:
        for guildid in config.AuthorisedGuilds:
            self.tree.copy_global_to( guild = discord.Object(id=guildid) )
            await self.tree.sync( guild = discord.Object(id=guildid) )

Intents = discord.Intents.all()
DiscordClient = DiscordBot(intents=Intents)

@DiscordClient.event
async def on_ready():
    logging.info(f"Logged in as {DiscordClient.user} ({DiscordClient.user.id})")

@DiscordClient.tree.command(name="ping", description="Pings the Vortexi website, and returns the response time.")
async def ping( interaction: discord.Interaction ):
    """
    Pings the Syntax backend server, and returns the response time.
    """
    RequestSession = await GetRequestSession()
    StartTime = time.time()
    try:
        RequestSession.get(FormatBackendUrl("Ping"))
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to ping the Vortexi website maybe it's down?",
            color=discord.Color.red()
        ))
        return
    
    await interaction.response.send_message(embed = discord.Embed(
         title="Pong!",
         description=f"Vortexi website responded in `{round(time.time() - StartTime, 3)}s`",
         color=discord.Color.green()
    ))

@DiscordClient.tree.command(name="lookup-username", description="Searches Vortexi for a user with the given username.")
@app_commands.describe(username="Searches Vortexi for a user with the given username.")
async def lookup_username( interaction: discord.Interaction, username: str ):
    """
    Requests info from the Syntax website about a user with the given username.
    """
    RequestSession = await GetRequestSession()
    try:
        RequestResponse = RequestSession.get(FormatBackendUrl(f"UsernameLookup"), params={"username": username})
        RequestResponse.raise_for_status()
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to lookup the username `{username}` maybe the Vortexi website is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        await interaction.response.send_message(embed = discord.Embed(
            title="User not found",
            description=f"Could not find a user with the username `{username}`, Response: `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    UserObject = RequestResponseJson["data"]
    UserEmbed = await BuildUserEmbed(UserObject)

    await interaction.response.send_message(embed = UserEmbed)

@DiscordClient.tree.command(name="lookup-userid", description="Searches Vortexi for a user with the given userId.")
@app_commands.describe(userid="Searches Vortexi for a user with the given userId.")
async def lookup_userid( interaction: discord.Interaction, userid: int ):
    """
    Requests info from the Syntax website about a user with the given userId.
    """
    RequestSession = await GetRequestSession()
    try:
        RequestResponse = RequestSession.get(FormatBackendUrl(f"UseridLookup"), params={"userid": userid})
        RequestResponse.raise_for_status()
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to lookup the userId `{userid}` maybe the Vortexi website is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        await interaction.response.send_message(embed = discord.Embed(
            title="User not found",
            description=f"Could not find a user with the userId `{userid}`, Response: `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    UserObject = RequestResponseJson["data"]
    UserEmbed = await BuildUserEmbed(UserObject)

    await interaction.response.send_message(embed = UserEmbed)

@DiscordClient.tree.command(name="lookup-user", description="Searches Vortexi for a user with the given member.")
@app_commands.describe(member="Searches Vortexi for a user with the given member.")
async def lookup_user( interaction: discord.Interaction, member: discord.Member ):
    """
    Requests info from the Syntax website about a user with the given member.
    """
    RequestSession = await GetRequestSession()
    try:
        RequestResponse = RequestSession.get(FormatBackendUrl(f"UserLookupByDiscordId"), params={"discordid": member.id})
        RequestResponse.raise_for_status()
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to lookup the account for <@{member.id}> maybe the Vortexi website is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        await interaction.response.send_message(embed = discord.Embed(
            title="User not found",
            description=f"Could not find a account linked to <@{member.id}> , Response: `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    UserObject = RequestResponseJson["data"]
    UserEmbed = await BuildUserEmbed(UserObject)

    await interaction.response.send_message(embed = UserEmbed)

@DiscordClient.tree.command(name="lookup-item", description="Searches Vortexi for an item with the given itemid.")
@app_commands.describe(itemid="Searches Vortexi for an item with the given itemid.")
async def lookup_item( interaction: discord.Interaction, itemid: int ):
    RequestSession = await GetRequestSession()
    try:
        RequestResponse = RequestSession.get(FormatBackendUrl(f"ItemLookup"), params={"itemid": itemid})
        RequestResponse.raise_for_status()
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to lookup for Item `{itemid}` maybe the Vortexi website is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        await interaction.response.send_message(embed = discord.Embed(
            title="Item not found",
            description=f"Could not find a Item with the ItemId `{itemid}`, Response: `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    ItemObject = RequestResponseJson["data"]
    ItemEmbed = await BuildItemEmbed(ItemObject)
    await interaction.response.send_message(embed = ItemEmbed)

@DiscordClient.tree.command(name="claim-roles", description="Claims your roles from the Vortexi website.")
async def claim_roles( interaction: discord.Interaction ):
    RequestSession = await GetRequestSession()
    UserDiscordId = interaction.user.id
    try:
        RequestResponse = RequestSession.get(FormatBackendUrl(f"UserLookupByDiscordId"), params={"discordid": UserDiscordId})
        RequestResponse.raise_for_status()
    except Exception as e:
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to retrieve info about you, maybe the Vortexi website is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        # User does not have an account linked to their discord, so remove their Verified Role and OBC role if they have it.
        UserRoles : list[discord.Role] = interaction.user.roles
        if config.VerifiedRoleId in [role.id for role in UserRoles]:
            await interaction.user.remove_roles(discord.Object(id=config.VerifiedRoleId))
        if config.OBCRoleId in [role.id for role in UserRoles]:
            await interaction.user.remove_roles(discord.Object(id=config.OBCRoleId))
        await interaction.response.send_message(embed = discord.Embed(
            title="User not found",
            description=f"Could not find a account linked to you, Response: `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    UserObject = RequestResponseJson["data"]
    UserRoles : list[discord.Role] = interaction.user.roles
    if UserObject["membership"] == "OutrageousBuildersClub":
        if config.OBCRoleId not in [role.id for role in UserRoles]:
            await interaction.user.add_roles(discord.Object(id=config.OBCRoleId))
    else:
        if config.OBCRoleId in [role.id for role in UserRoles]:
            await interaction.user.remove_roles(discord.Object(id=config.OBCRoleId))
    if config.VerifiedRoleId not in [role.id for role in UserRoles]:
        await interaction.user.add_roles(discord.Object(id=config.VerifiedRoleId))
    await interaction.user.edit(nick=UserObject["username"])

    await interaction.response.send_message(embed = discord.Embed(
        title=f"Hello, {UserObject['username']}!",
        description=f"Your roles have been updated!",
        color=discord.Color.green()
    ))

@DiscordClient.tree.command(name="claim-turbo", description="Claim your Turbo Builders Club after boosting the server. ( Must have a linked Vortexi Account )")
async def claim_turbo( interaction: discord.Interaction ):
    UserRoles : list[discord.Role] = interaction.user.roles
    if config.ServerBoosterRole not in [role.id for role in UserRoles]:
        await interaction.response.send_message(embed = discord.Embed(
            title="You shall not past!",
            description=f"You must boost the server to claim Turbo Builders Club!",
            color=discord.Color.red()
        ))
        return

    RequestSession = await GetRequestSession()
    UserDiscordId = interaction.user.id
    try:
        RequestResponse = RequestSession.post(FormatBackendUrl(f"AwardUserTurbo"), params={"discordid": UserDiscordId})
        RequestResponse.raise_for_status()
    except Exception as e:
        logging.error(e)
        await interaction.response.send_message(embed = discord.Embed(
            title="Error! :(",
            description=f"An error occured while trying to contact the Vortexi website, maybe Vortexi is down?",
            color=discord.Color.red()
        ))
        return
    
    RequestResponseJson = RequestResponse.json()
    if RequestResponseJson["success"] == False:
        await interaction.response.send_message(embed = discord.Embed(
            title="Failed :(",
            description=f"We were unable to give you Turbo Builders Club because `{RequestResponseJson['message']}`",
            color=discord.Color.red()
        ))
        return
    await interaction.response.send_message(embed = discord.Embed(
        title="Success!",
        description=f"You have been given 2 Weeks of Turbo Builders Club! If your membership expires run this command again to renew it.",
        color=discord.Color.green()
    ))

DiscordClient.run(config.DiscordBotToken)
