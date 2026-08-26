import os
import io
import re
import json
import random
import asyncio
import logging
import aiosqlite
import aiohttp
import feedparser
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Chargement du token via .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")

# ==========================================
# INTERFACES INTERACTIVES (VIEWS & MODALS)
# ==========================================

# Assistant Créateur de Serveur pas-à-pas (IA Lia)
class ServerSetupModal(ui.Modal, title="Lia • Assistant de Création RP"):
    server_type = ui.TextInput(label="Type de Serveur", placeholder="Ex: Serious RP, Semi-RP, Freeroam", default="Serious RP")
    categories = ui.TextInput(label="Catégories (séparées par des virgules)", placeholder="INFORMATIONS, ZONE HRP, ZONE RP, SERVICES", style=discord.TextStyle.paragraph)
    roles = ui.TextInput(label="Rôles Clés (séparés par des virgules)", placeholder="Fondateur, Staff, Police, EMS, Citoyen", style=discord.TextStyle.paragraph)
    channels = ui.TextInput(label="Salons Principaux", placeholder="reglement, annonce, hrp-chat, commande-boutique", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏗️ Aperçu de la Structure Proposée par Lia",
            description=f"**Thématique :** {self.server_type.value}\n\n"
                        f"**Catégories :** {self.categories.value}\n"
                        f"**Rôles :** {self.roles.value}\n"
                        f"**Salons Exemple :** {self.channels.value}",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Validation requise avant déploiement.")
        view = ConfirmServerBuildView(self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmServerBuildView(ui.View):
    def __init__(self, data: ServerSetupModal):
        super().__init__(timeout=300)
        self.data = data

    @ui.button(label="Confirmer & Générer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("⚙️ Lia déploie l'architecture du serveur...", ephemeral=True)
        guild = interaction.guild

        roles_list = [r.strip() for r in self.data.roles.value.split(",") if r.strip()]
        for r_name in roles_list:
            if not discord.utils.get(guild.roles, name=r_name):
                await guild.create_role(name=r_name, reason="Lia Auto-Setup")

        cat_list = [c.strip() for c in self.data.categories.value.split(",") if c.strip()]
        chan_list = [ch.strip() for ch in self.data.channels.value.split(",") if ch.strip()]

        for c_name in cat_list:
            category = discord.utils.get(guild.categories, name=c_name)
            if not category:
                category = await guild.create_category(c_name)
            for ch_name in chan_list:
                if not discord.utils.get(category.text_channels, name=ch_name):
                    await guild.create_text_channel(name=ch_name, category=category)

        await interaction.followup.send("🎉 Déploiement terminé sans doublons !", ephemeral=True)

    @ui.button(label="Annuler", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("❌ Action annulée par l'administrateur.", ephemeral=True)

# Panneau /config interactif
class ConfigMainSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Bienvenue", emoji="👋", value="welcome"),
            discord.SelectOption(label="Au Revoir", emoji="🚪", value="leave"),
            discord.SelectOption(label="Auto-Rôle", emoji="🤖", value="autorole"),
            discord.SelectOption(label="Logs Système", emoji="📋", value="logs"),
            discord.SelectOption(label="Vérification", emoji="🔐", value="verify"),
            discord.SelectOption(label="Tickets & Support", emoji="🎫", value="tickets")
        ]
        super().__init__(placeholder="Sélectionnez une section à configurer...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selection = self.values[0]
        guild = interaction.guild

        if selection == "welcome":
            await interaction.response.send_modal(WelcomeConfigModal())
        elif selection == "leave":
            await interaction.response.send_modal(LeaveConfigModal())
        elif selection == "autorole":
            view = RoleSelectView("autorole")
            await interaction.response.send_message("Choisissez le rôle attribué aux nouveaux arrivants :", view=view, ephemeral=True)
        elif selection == "logs":
            view = ChannelSelectView("logs")
            await interaction.response.send_message("Choisissez le salon de journalisation des logs :", view=view, ephemeral=True)
        elif selection == "verify":
            view = RoleSelectView("verify")
            await interaction.response.send_message("Choisissez le rôle donné après vérification :", view=view, ephemeral=True)
        else:
            await interaction.response.send_message(f"⚙️ Module `{selection}` accessible via les commandes dédiées.", ephemeral=True)

class WelcomeConfigModal(ui.Modal, title="Configuration du Message de Bienvenue"):
    msg = ui.TextInput(label="Message ({user}, {server}, {member_count})", style=discord.TextStyle.paragraph, default="👋 Bienvenue {user} sur {server} ! Nous sommes {member_count} membres.")
    color = ui.TextInput(label="Couleur Hex (#00FF00)", default="#00FF00")
    image = ui.TextInput(label="URL de l'image (Optionnel)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            c_int = int(self.color.value.replace("#", ""), 16)
        except ValueError:
            c_int = 65280

        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                INSERT INTO guild_config (guild_id, welcome_message, welcome_color, welcome_image)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    welcome_message=excluded.welcome_message,
                    welcome_color=excluded.welcome_color,
                    welcome_image=excluded.welcome_image
            """, (interaction.guild.id, self.msg.value, c_int, self.image.value))
            await db.commit()

        await interaction.response.send_message("✅ Configuration de Bienvenue sauvegardée !", ephemeral=True)

class LeaveConfigModal(ui.Modal, title="Configuration du Message de Départ"):
    msg = ui.TextInput(label="Message ({username}, {server})", style=discord.TextStyle.paragraph, default="👋 {username} a quitté {server}. À bientôt !")
    color = ui.TextInput(label="Couleur Hex (#FF0000)", default="#FF0000")
    image = ui.TextInput(label="URL de l'image (Optionnel)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            c_int = int(self.color.value.replace("#", ""), 16)
        except ValueError:
            c_int = 16711680

        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                INSERT INTO guild_config (guild_id, leave_message, leave_color, leave_image)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    leave_message=excluded.leave_message,
                    leave_color=excluded.leave_color,
                    leave_image=excluded.leave_image
            """, (interaction.guild.id, self.msg.value, c_int, self.image.value))
            await db.commit()

        await interaction.response.send_message("✅ Configuration Au Revoir sauvegardée !", ephemeral=True)

class RoleSelectView(ui.View):
    def __init__(self, target_type):
        super().__init__()
        self.target_type = target_type
        select = ui.RoleSelect(placeholder="Sélectionner un rôle...")
        select.callback = self.role_callback
        self.add_item(select)

    async def role_callback(self, interaction: discord.Interaction):
        role_id = interaction.data["values"][0]
        async with aiosqlite.connect("database.db") as db:
            if self.target_type == "autorole":
                await db.execute("INSERT INTO guild_config (guild_id, auto_roles) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET auto_roles=excluded.auto_roles", (interaction.guild.id, str(role_id)))
            elif self.target_type == "verify":
                await db.execute("INSERT INTO guild_config (guild_id, verify_role) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET verify_role=excluded.verify_role", (interaction.guild.id, int(role_id)))
            await db.commit()
        await interaction.response.send_message("✅ Rôle mis à jour !", ephemeral=True)

class ChannelSelectView(ui.View):
    def __init__(self, target_type):
        super().__init__()
        self.target_type = target_type
        select = ui.ChannelSelect(placeholder="Sélectionner un salon...", channel_types=[discord.ChannelType.text])
        select.callback = self.channel_callback
        self.add_item(select)

    async def channel_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data["values"][0])
        async with aiosqlite.connect("database.db") as db:
            if self.target_type == "logs":
                await db.execute("INSERT INTO guild_config (guild_id, log_channel) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET log_channel=excluded.log_channel", (interaction.guild.id, channel_id))
            elif self.target_type == "welcome_chan":
                await db.execute("INSERT INTO guild_config (guild_id, welcome_channel) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET welcome_channel=excluded.welcome_channel", (interaction.guild.id, channel_id))
            elif self.target_type == "leave_chan":
                await db.execute("INSERT INTO guild_config (guild_id, leave_channel) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET leave_channel=excluded.leave_channel", (interaction.guild.id, channel_id))
            await db.commit()
        await interaction.response.send_message(f"✅ Salon <#{channel_id}> enregistré !", ephemeral=True)

# Tickets & Transcripts
class TicketActionView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="tk_close_btn")
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("🔒 Clôture du ticket et archivage en cours...", ephemeral=True)
        
        history = [m async for m in interaction.channel.history(limit=1000, oldest_first=True)]
        content = f"--- TRANSCRIPT TICKET {interaction.channel.name} ---\n\n"
        for m in history:
            content += f"[{m.created_at.strftime('%d/%m/%Y %H:%M')}] {m.author}: {m.content}\n"
            
        file = discord.File(io.BytesIO(content.encode("utf-8")), filename=f"{interaction.channel.name}.txt")

        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT logs_id FROM ticket_config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    log_chan = interaction.guild.get_channel(row[0])
                    if log_chan:
                        await log_chan.send(content=f"Transcript du ticket fermé par {interaction.user.mention}:", file=file)

        await interaction.channel.delete()

    @ui.button(label="Prendre en charge", style=discord.ButtonStyle.success, emoji="✋", custom_id="tk_claim_btn")
    async def claim(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"✋ Ticket pris en charge par {interaction.user.mention}.")

class TicketSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Basique", emoji="🎫", value="basic"),
            discord.SelectOption(label="Candidature RP", emoji="📝", value="candidature"),
            discord.SelectOption(label="Demande Personnalisée", emoji="⚙️", value="custom")
        ]
        super().__init__(placeholder="Choisissez le type de ticket...", custom_id="tk_select_menu_main", options=options)

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        val = self.values[0]

        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT category_id FROM ticket_config WHERE guild_id = ?", (guild.id,)) as cursor:
                row = await cursor.fetchone()
                category = guild.get_channel(row[0]) if row and row[0] else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        chan = await guild.create_text_channel(name=f"ticket-{val}-{user.name}", category=category, overwrites=overwrites)
        
        embed = discord.Embed(
            title=f"🎫 Support — {val.capitalize()}",
            description=f"Bonjour {user.mention}, posez vos questions ici. Le Staff intervient sous peu.",
            color=discord.Color.blue()
        )
        await chan.send(embed=embed, view=TicketActionView())
        await interaction.response.send_message(f"✅ Ticket ouvert : {chan.mention}", ephemeral=True)

# Modale Annonce
class AnnouncementModal(ui.Modal, title="Créateur d'Annonce Pro"):
    title_in = ui.TextInput(label="Titre")
    desc_in = ui.TextInput(label="Contenu principal", style=discord.TextStyle.paragraph)
    color_in = ui.TextInput(label="Couleur Hex (#FF0000)", default="#00FF88", required=False)
    image_in = ui.TextInput(label="URL Image Grand Format", required=False)

    def __init__(self, target_channel: discord.TextChannel, role_mention: discord.Role = None):
        super().__init__()
        self.target_channel = target_channel
        self.role_mention = role_mention

    async def on_submit(self, interaction: discord.Interaction):
        try:
            col = int(self.color_in.value.replace("#", ""), 16)
        except ValueError:
            col = discord.Color.blue().value

        embed = discord.Embed(title=self.title_in.value, description=self.desc_in.value, color=col)
        embed.set_footer(text=f"Publication officielle • {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        if self.image_in.value:
            embed.set_image(url=self.image_in.value)

        content = self.role_mention.mention if self.role_mention else None
        await self.target_channel.send(content=content, embed=embed)
        await interaction.response.send_message("✅ Annonce publiée avec succès !", ephemeral=True)

# Vérification Bouton
class VerificationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="S'inscrire / Valider le Règlement", style=discord.ButtonStyle.success, emoji="✅", custom_id="verify_main_btn")
    async def verify(self, interaction: discord.Interaction, button: ui.Button):
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT verify_role FROM guild_config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    role = interaction.guild.get_role(row[0])
                    if role:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message("✅ Vous avez été vérifié et avez reçu l'accès !", ephemeral=True)
                        return
        await interaction.response.send_message("❌ Le rôle de vérification n'est pas configuré sur ce serveur.", ephemeral=True)


# ==========================================
# BOT PRINCIPAL & EVENT LOOP
# ==========================================

class LiaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = True
        
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.init_db()
        await self.tree.sync()
        print("✅ Commandes Slash synchronisées à l'échelle globale.")

    async def init_db(self):
        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel INTEGER,
                    welcome_channel INTEGER,
                    welcome_message TEXT,
                    welcome_color INTEGER DEFAULT 65280,
                    welcome_image TEXT,
                    leave_channel INTEGER,
                    leave_message TEXT,
                    leave_color INTEGER DEFAULT 16711680,
                    leave_image TEXT,
                    auto_roles TEXT,
                    maintenance BOOLEAN DEFAULT 0,
                    verify_role INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_config (
                    guild_id INTEGER PRIMARY KEY,
                    category_id INTEGER,
                    logs_id INTEGER,
                    staff_role_id INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS social_feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    platform TEXT,
                    channel_identifier TEXT,
                    target_channel_id INTEGER,
                    custom_message TEXT,
                    last_post_id TEXT
                )
            """)
            await db.commit()

bot = LiaBot()

# Arrivée du Bot sur un Serveur (Message d'Accueil dans #general)
@bot.event
async def on_guild_join(guild: discord.Guild):
    target_channel = discord.utils.get(guild.text_channels, name="general")
    if not target_channel or not target_channel.permissions_for(guild.me).send_messages:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                target_channel = channel
                break
                
    if target_channel:
        embed = discord.Embed(
            title="👋 Merci d'avoir ajouté ORAN RP !",
            description=(
                "Je suis **Lia**, ton assistante Discord autonome et intelligente.\n\n"
                "Je peux gérer vos **tickets, annonces, systèmes de bienvenue/départ, modération, "
                "réseaux sociaux (YouTube, Twitch...), sauvegardes** et bien plus encore.\n\n"
                "👉 Tapez `/config` pour ouvrir le panneau de configuration interactif complet."
            ),
            color=discord.Color.from_rgb(255, 105, 180)
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        await target_channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f" Connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Oran RP | /config"))
    if not check_social_feeds.is_running():
        check_social_feeds.start()

# Événement d'arrivée d'un membre (Bienvenue & Auto-Rôle)
@bot.event
async def on_member_join(member: discord.Member):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT welcome_channel, welcome_message, welcome_color, welcome_image, auto_roles FROM guild_config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                w_chan, w_msg, w_col, w_img, a_role = row

                if a_role:
                    role = member.guild.get_role(int(a_role))
                    if role:
                        await member.add_roles(role)

                if w_chan:
                    channel = member.guild.get_channel(w_chan)
                    if channel:
                        formatted_msg = (w_msg or "Bienvenue {user} !").format(
                            user=member.mention,
                            username=member.name,
                            server=member.guild.name,
                            member_count=member.guild.member_count
                        )
                        embed = discord.Embed(description=formatted_msg, color=w_col or 65280)
                        if w_img:
                            embed.set_image(url=w_img)
                        embed.set_thumbnail(url=member.display_avatar.url)
                        await channel.send(embed=embed)

# Événement de départ d'un membre (Au Revoir)
@bot.event
async def on_member_remove(member: discord.Member):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT leave_channel, leave_message, leave_color, leave_image FROM guild_config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                l_chan, l_msg, l_col, l_img = row
                channel = member.guild.get_channel(l_chan)
                if channel:
                    formatted_msg = (l_msg or "Au revoir {username} !").format(
                        user=member.mention,
                        username=member.name,
                        server=member.guild.name,
                        member_count=member.guild.member_count
                    )
                    embed = discord.Embed(description=formatted_msg, color=l_col or 16711680)
                    if l_img:
                        embed.set_image(url=l_img)
                    await channel.send(embed=embed)

# Interception du Langage Naturel ("Oran RP ...")
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    clean_text = re.sub(r'[^\w\s]', '', message.content.lower())
    
    if clean_text.startswith("oran rp"):
        if any(kw in clean_text for kw in ["fait moi un serveur", "cree un serveur", "fais moi un serveur", "creer serveur"]):
            if not message.author.guild_permissions.administrator:
                await message.channel.send("❌ Seuls les administrateurs peuvent utiliser cette fonction.")
                return

            view = ui.View()
            btn = ui.Button(label="Lancer l'assistant de création", style=discord.ButtonStyle.primary, emoji="🤖")
            
            async def callback(interaction: discord.Interaction):
                await interaction.response.send_modal(ServerSetupModal())

            btn.callback = callback
            view.add_item(btn)
            await message.channel.send(f"Bonjour {message.author.mention}, je suis **Lia**. Cliquez ci-dessous pour configurer votre serveur RP.", view=view)
            return
            
        elif "fais une annonce" in clean_text or "cree une annonce" in clean_text:
            await message.channel.send("📢 Pour créer une annonce, utilisez la commande slash `/annonce` !")
            return

        elif "cree un ticket" in clean_text or "active les tickets" in clean_text:
            await message.channel.send("🎫 Pour installer le panneau de tickets, utilisez `/ticket` !")
            return

    await bot.process_commands(message)


# ==========================================
# VÉRIFICATEUR SOCIALS (YOUTUBE / FEEDS)
# ==========================================

@tasks.loop(minutes=5)
async def check_social_feeds():
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT id, guild_id, platform, channel_identifier, target_channel_id, custom_message, last_post_id FROM social_feeds") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                feed_id, guild_id, platform, chan_id, target_chan_id, msg, last_post = row
                
                if platform.lower() == "youtube":
                    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={chan_id}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                xml_data = await resp.text()
                                feed = feedparser.parse(xml_data)
                                if feed.entries:
                                    latest = feed.entries[0]
                                    if latest.id != last_post:
                                        guild = bot.get_guild(guild_id)
                                        if guild:
                                            target = guild.get_channel(target_chan_id)
                                            if target:
                                                embed = discord.Embed(
                                                    title=f"🔴 Nouvelle vidéo : {latest.title}",
                                                    url=latest.link,
                                                    color=discord.Color.red()
                                                )
                                                embed.set_author(name="YouTube Update")
                                                await target.send(content=msg or "Nouvelle vidéo disponible !", embed=embed)
                                        
                                        await db.execute("UPDATE social_feeds SET last_post_id = ? WHERE id = ?", (latest.id, feed_id))
                                        await db.commit()


# ==========================================
# COMMANDES SLASH DE MODÉRATION & GESTION
# ==========================================

# Helper pour les logs de modération
async def log_mod_action(guild: discord.Guild, embed: discord.Embed):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT log_channel FROM guild_config WHERE guild_id = ?", (guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                chan = guild.get_channel(row[0])
                if chan:
                    await chan.send(embed=embed)

@bot.tree.command(name="config", description="Panneau de configuration général du serveur")
@app_commands.checks.has_permissions(administrator=True)
async def config_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Panneau de Configuration Central — ORAN RP",
        description="Utilisez le menu déroulant ci-dessous pour configurer Lia et le serveur.",
        color=discord.Color.dark_purple()
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    view = ui.View()
    view.add_item(ConfigMainSelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="annonce", description="Créer une annonce professionnelle")
@app_commands.checks.has_permissions(manage_messages=True)
async def create_annonce(interaction: discord.Interaction, salon: discord.TextChannel, role_a_mentionner: discord.Role = None):
    await interaction.response.send_modal(AnnouncementModal(target_channel=salon, role_mention=role_a_mentionner))

@bot.tree.command(name="ticket", description="Afficher le panneau de création de tickets")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Centre de Support — ORAN RP",
        description="Sélectionnez le type de ticket désiré dans le menu ci-dessous.",
        color=discord.Color.red()
    )
    view = ui.View()
    view.add_item(TicketSelectMenu())
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="verification", description="Poser le panneau de vérification avec bouton")
@app_commands.checks.has_permissions(administrator=True)
async def verify_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔐 Accès & Vérification — ORAN RP",
        description="Cliquez sur le bouton ci-dessous pour accepter le règlement et débloquer les salons.",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=VerificationView())
    await interaction.response.send_message("✅ Panneau de vérification placé !", ephemeral=True)

@bot.tree.command(name="clear", description="Purge un nombre de messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, nombre: int):
    deleted = await interaction.channel.purge(limit=nombre)
    await interaction.response.send_message(f"🗑️ {len(deleted)} messages supprimés.", ephemeral=True)

@bot.tree.command(name="lock", description="Verrouiller le salon")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Salon verrouillé.")

@bot.tree.command(name="unlock", description="Déverrouiller le salon")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Salon déverrouillé.")

@bot.tree.command(name="warn", description="Attribuer un avertissement")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, membre: discord.Member, raison: str):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                         (interaction.guild.id, membre.id, interaction.user.id, raison))
        await db.commit()

    embed = discord.Embed(title="⚠️ Sanction : Avertissement", color=discord.Color.gold())
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)
    await log_mod_action(interaction.guild, embed)

@bot.tree.command(name="kick", description="Expulser un membre")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.kick(reason=raison)
    embed = discord.Embed(title="👞 Sanction : Expulsion", color=discord.Color.orange())
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Raison", value=raison)
    await interaction.response.send_message(embed=embed)
    await log_mod_action(interaction.guild, embed)

@bot.tree.command(name="ban", description="Bannir un membre")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.ban(reason=raison)
    embed = discord.Embed(title="🔨 Sanction : Bannissement", color=discord.Color.red())
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Raison", value=raison)
    await interaction.response.send_message(embed=embed)
    await log_mod_action(interaction.guild, embed)

@bot.tree.command(name="suggestion", description="Proposer une idée pour le serveur")
async def suggestion(interaction: discord.Interaction, idee: str):
    embed = discord.Embed(title="💡 Nouvelle Suggestion RP", description=idee, color=discord.Color.gold())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    
    view = ui.View()
    btn_up = ui.Button(label="0", style=discord.ButtonStyle.success, emoji="👍")
    btn_down = ui.Button(label="0", style=discord.ButtonStyle.danger, emoji="👎")
    
    async def up_cb(i: discord.Interaction):
        btn_up.label = str(int(btn_up.label) + 1)
        await i.response.edit_message(view=view)
        
    async def down_cb(i: discord.Interaction):
        btn_down.label = str(int(btn_down.label) + 1)
        await i.response.edit_message(view=view)

    btn_up.callback = up_cb
    btn_down.callback = down_cb
    view.add_item(btn_up)
    view.add_item(btn_down)

    await interaction.response.send_message("✅ Suggestion transmise !", ephemeral=True)
    await interaction.channel.send(embed=embed, view=view)

@bot.tree.command(name="backup", description="Télécharger une sauvegarde JSON de la structure")
@app_commands.checks.has_permissions(administrator=True)
async def backup(interaction: discord.Interaction):
    guild = interaction.guild
    data = {
        "server_name": guild.name,
        "roles": [{"name": r.name, "permissions": r.permissions.value} for r in guild.roles if not r.is_default()],
        "categories": [{"name": c.name} for c in guild.categories],
        "channels": [{"name": ch.name, "type": str(ch.type)} for ch in guild.channels]
    }
    
    file_bytes = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
    file = discord.File(io.BytesIO(file_bytes), filename=f"backup_oranrp_{guild.id}.json")
    await interaction.response.send_message("💾 Sauvegarde générée avec succès par Lia :", file=file, ephemeral=True)

# Lancement global
if __name__ == "__main__":
    if not TOKEN:
        print("CRITICAL: DISCORD_TOKEN n'est pas configuré dans le fichier .env")
    else:
        bot.run(TOKEN)
