import os
import io
import re
import json
import asyncio
import logging
import datetime
import aiosqlite
import aiohttp
import feedparser
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s")

# ==========================================
# BDD & INITIALISATION ASYNCHRONE
# ==========================================

async def init_db():
    async with aiosqlite.connect("database.db") as db:
        # Configuration globale
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
                verify_role INTEGER,
                general_channel INTEGER,
                staff_role INTEGER,
                game_cfx_id TEXT,
                game_name TEXT,
                game_link TEXT
            )
        """)
        # Configuration des tickets
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                logs_id INTEGER,
                staff_role_id INTEGER
            )
        """)
        # Questions personnalisées pour candidatures
        await db.execute("""
            CREATE TABLE IF NOT EXISTS application_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                question_text TEXT
            )
        """)
        # Modération & Sanctions
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
        # Flux Réseaux Sociaux
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


# ==========================================
# MODALES & VUES D'ADMINISTRATION & TICKETS
# ==========================================

# Modale : Ajout de question aux candidatures
class AddQuestionModal(ui.Modal, title="Ajouter une Question de Candidature"):
    question = ui.TextInput(label="Libellé de la question", style=discord.TextStyle.paragraph, placeholder="Ex: Quels sont vos atouts RP ?")

    async def on_submit(self, interaction: discord.Interaction):
        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT INTO application_questions (guild_id, question_text) VALUES (?, ?)", (interaction.guild.id, self.question.value))
            await db.commit()
        await interaction.response.send_message("✅ Question ajoutée avec succès aux candidatures !", ephemeral=True)

# Formulaire Dynamique de Candidature
class ApplicationModal(ui.Modal, title="Formulaire de Candidature RP"):
    def __init__(self, questions):
        super().__init__()
        self.inputs = []
        for i, q in enumerate(questions[:5]): # Max 5 champs sur Discord
            inp = ui.TextInput(label=q[1][:45], style=discord.TextStyle.paragraph, required=True)
            self.inputs.append((q[1], inp))
            self.add_item(inp)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT category_id, logs_id, staff_role_id FROM ticket_config WHERE guild_id = ?", (guild.id,)) as cursor:
                row = await cursor.fetchone()
                category_id, logs_id, staff_role_id = row if row else (None, None, None)

        category = guild.get_channel(category_id) if category_id else None
        staff_role = guild.get_role(staff_role_id) if staff_role_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        chan = await guild.create_text_channel(name=f"candid-{interaction.user.name}", category=category, overwrites=overwrites)
        
        embed = discord.Embed(
            title=f"📝 Candidature RP — {interaction.user.display_name}",
            description="Voici les réponses soumises par le candidat :",
            color=discord.Color.gold()
        )
        for q_text, inp in self.inputs:
            embed.add_field(name=q_text, value=inp.value, inline=False)

        await chan.send(embed=embed, view=ApplicationReviewView(applicant=interaction.user))
        await interaction.response.send_message(f"✅ Candidature envoyée dans {chan.mention} !", ephemeral=True)

# Gestion de la Candidature par le Staff
class ApplicationReviewView(ui.View):
    def __init__(self, applicant: discord.Member):
        super().__init__(timeout=None)
        self.applicant = applicant

    @ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"🎉 La candidature de {self.applicant.mention} a été **ACCEPTÉE** par {interaction.user.mention}.")
        try:
            await self.applicant.send(f"🎉 Félicitations ! Votre candidature sur **{interaction.guild.name}** a été acceptée.")
        except Exception:
            pass

    @ui.button(label="Refuser", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"❌ La candidature de {self.applicant.mention} a été **REFUSÉE** par {interaction.user.mention}.")
        try:
            await self.applicant.send(f"❌ Malheureusement, votre candidature sur **{interaction.guild.name}** n'a pas été retenue.")
        except Exception:
            pass

    @ui.button(label="Contacter", style=discord.ButtonStyle.primary, emoji="💬")
    async def contact(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"💬 {interaction.user.mention} souhaite échanger avec {self.applicant.mention} concernant sa candidature.")

# Menu déroulant de sélection pour les Tickets
class TicketSelectMenu(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Support General", emoji="🎫", value="basic"),
            discord.SelectOption(label="Candidature RP", emoji="📝", value="candidature"),
            discord.SelectOption(label="Demande Personnalisee", emoji="⚙️", value="custom")
        ]
        super().__init__(placeholder="Choisissez le type de demande...", custom_id="tk_select_menu_main", options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "candidature":
            async with aiosqlite.connect("database.db") as db:
                async with db.execute("SELECT id, question_text FROM application_questions WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                    questions = await cursor.fetchall()
            
            if not questions:
                # Questions par défaut si aucune n'a été ajoutée
                questions = [(0, "Nom & Âge RP/HRP"), (0, "Vos motivations"), (0, "Votre histoire RP")]
            
            await interaction.response.send_modal(ApplicationModal(questions))
        else:
            guild = interaction.guild
            user = interaction.user
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
            embed = discord.Embed(title=f"🎫 Support — {val.capitalize()}", description=f"Bonjour {user.mention}, posez votre question. L'équipe Staff va intervenir.", color=discord.Color.blue())
            
            view = ui.View()
            btn_close = ui.Button(label="Fermer & Transcript", style=discord.ButtonStyle.danger, emoji="🔒")
            
            async def close_cb(i: discord.Interaction):
                history = [m async for m in chan.history(limit=1000, oldest_first=True)]
                content = f"--- TRANSCRIPT DE {chan.name} ---\n\n" + "\n".join([f"[{m.created_at.strftime('%Y-%m-%d %H:%M')}] {m.author}: {m.content}" for m in history])
                file = discord.File(io.BytesIO(content.encode("utf-8")), filename=f"{chan.name}.txt")
                
                async with aiosqlite.connect("database.db") as db:
                    async with db.execute("SELECT logs_id FROM ticket_config WHERE guild_id = ?", (guild.id,)) as cursor:
                        r = await cursor.fetchone()
                        if r and r[0]:
                            log_c = guild.get_channel(r[0])
                            if log_c: await log_c.send(content="Transcript du ticket :", file=file)
                await chan.delete()

            btn_close.callback = close_cb
            view.add_item(btn_close)
            await chan.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Ticket ouvert dans {chan.mention}", ephemeral=True)

# Panneau /admin interactif complet
class AdminDashboardView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(
        placeholder="Menu Administration ORAN RP...",
        options=[
            discord.SelectOption(label="Configuration Generale", emoji="⚙️", value="config"),
            discord.SelectOption(label="Tickets & Support", emoji="🎫", value="tickets"),
            discord.SelectOption(label="Candidatures (Questions)", emoji="📝", value="candidatures"),
            discord.SelectOption(label="Bienvenue & Au Revoir", emoji="👋", value="welcome"),
            discord.SelectOption(label="Logs & Modération", emoji="📋", value="logs"),
            discord.SelectOption(label="Informations Jeu (CFX)", emoji="🎮", value="game"),
            discord.SelectOption(label="Réseaux Sociaux", emoji="📺", value="socials")
        ]
    )
    async def select_menu(self, interaction: discord.Interaction, select: ui.Select):
        val = select.values[0]
        if val == "candidatures":
            view = ui.View()
            btn_add = ui.Button(label="Ajouter une Question", style=discord.ButtonStyle.success, emoji="➕")
            async def add_cb(i: discord.Interaction):
                await i.response.send_modal(AddQuestionModal())
            btn_add.callback = add_cb
            view.add_item(btn_add)
            await interaction.response.send_message("📝 Gestionnaire des questions de candidature :", view=view, ephemeral=True)
            
        elif val == "game":
            modal = GameConfigModal()
            await interaction.response.send_modal(modal)
            
        elif val == "tickets":
            embed = discord.Embed(title="⚙️ Configuration des Tickets", description="Placez le panneau de tickets dans le salon de votre choix avec `/ticket`.", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        else:
            await interaction.response.send_message(f"⚙️ Option `{val}` sélectionnée. Utilisez les commandes Slash associées pour affiner le paramétrage.", ephemeral=True)

class GameConfigModal(ui.Modal, title="Configuration API Jeu / FiveM"):
    cfx_id = ui.TextInput(label="ID CFX.re / FiveM (ex: cfx.re/join/XXXXXX)", placeholder="XXXXXX", required=False)
    game_name = ui.TextInput(label="Nom du Serveur RP", default="ORAN RP")
    game_link = ui.TextInput(label="Lien de Connexion / Discord", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                INSERT INTO guild_config (guild_id, game_cfx_id, game_name, game_link)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    game_cfx_id=excluded.game_cfx_id,
                    game_name=excluded.game_name,
                    game_link=excluded.game_link
            """, (interaction.guild.id, self.cfx_id.value, self.game_name.value, self.game_link.value))
            await db.commit()
        await interaction.response.send_message("✅ Configuration du jeu enregistrée !", ephemeral=True)

# Double Confirmation Réinitialisation
class DeleteServerConfirmView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @ui.button(label="CONFIRMER LA SUPPRESSION", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("🗑️ Suppression complète des éléments ORAN RP en cours...", ephemeral=True)
        guild = interaction.guild
        
        # Nettoyage BDD
        async with aiosqlite.connect("database.db") as db:
            await db.execute("DELETE FROM guild_config WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM ticket_config WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM application_questions WHERE guild_id = ?", (guild.id,))
            await db.commit()

        await interaction.followup.send("✅ La configuration du serveur a été entièrement réinitialisée.", ephemeral=True)

    @ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("❌ Réinitialisation annulée.", ephemeral=True)


# ==========================================
# BOT & EVENTS
# ==========================================

class LiaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await init_db()
        await self.tree.sync()
        print("✅ Commandes Slash synchronisées à l'échelle globale.")

bot = LiaBot()

@bot.event
async def on_ready():
    print(f"🤖 Bot connecté : {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Oran RP | /admin"))
    if not check_social_feeds.is_running():
        check_social_feeds.start()

@bot.event
async def on_member_join(member: discord.Member):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT welcome_channel, welcome_message, welcome_color, welcome_image, auto_roles FROM guild_config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                w_chan, w_msg, w_col, w_img, a_role = row
                if a_role:
                    role = member.guild.get_role(int(a_role))
                    if role: await member.add_roles(role)
                if w_chan:
                    chan = member.guild.get_channel(w_chan)
                    if chan:
                        msg = (w_msg or "Bienvenue {user} sur {server} !").format(
                            user=member.mention, username=member.name, server=member.guild.name, member_count=member.guild.member_count
                        )
                        embed = discord.Embed(description=msg, color=w_col or 65280)
                        if w_img: embed.set_image(url=w_img)
                        embed.set_thumbnail(url=member.display_avatar.url)
                        await chan.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    text = message.content.lower().strip()
    
    # Prise en charge poussée du Langage Naturel "Oran RP ..."
    if text.startswith("oran rp"):
        query = text.replace("oran rp", "").strip()
        
        if any(kw in query for kw in ["fais moi un serveur", "cree un serveur", "creer serveur"]):
            await message.channel.send("🚀 Tapez `/creer-server` pour générer automatiquement toute l'architecture du serveur RP !")
            return
            
        if "question" in query and "candidature" in query:
            view = ui.View()
            btn = ui.Button(label="Ajouter une question", style=discord.ButtonStyle.primary, emoji="📝")
            async def cb(i: discord.Interaction):
                await i.response.send_modal(AddQuestionModal())
            btn.callback = cb
            view.add_item(btn)
            await message.channel.send(f"Bonjour {message.author.mention}, cliquez ci-dessous pour ajouter une question :", view=view)
            return

        if "ticket" in query:
            await message.channel.send("🎫 Pour poser le panneau de support, utilisez `/ticket`.")
            return

        if "annonce" in query:
            await message.channel.send("📢 Pour créer une annonce, utilisez la commande `/annonce`.")
            return

        await message.channel.send(f"Bonjour {message.author.mention}, je suis **Lia**. Tapez `/admin` pour accéder à mon panneau complet.")
        return

    await bot.process_commands(message)


# ==========================================
# COMMANDES SLASH & NOUVELLES FONCTIONNALITÉS
# ==========================================

# 1. /creer-server
@bot.tree.command(name="creer-server", description="Générer automatiquement la structure complète du serveur RP")
@app_commands.checks.has_permissions(administrator=True)
async def creer_server(interaction: discord.Interaction):
    await interaction.response.send_message("⚙️ Création de l'architecture RP en cours...", ephemeral=True)
    guild = interaction.guild

    # Rôles principaux
    roles_data = [
        ("Fondateur", discord.Color.gold(), True),
        ("Staff / Admin", discord.Color.red(), True),
        ("Modérateur", discord.Color.blue(), True),
        ("Police", discord.Color.dark_blue(), False),
        ("EMS", discord.Color.green(), False),
        ("Citoyen", discord.Color.light_grey(), False)
    ]
    created_roles = {}
    for r_name, r_col, r_hoist in roles_data:
        r = discord.utils.get(guild.roles, name=r_name)
        if not r:
            r = await guild.create_role(name=r_name, color=r_col, hoist=r_hoist)
        created_roles[r_name] = r

    # Structure Catégories & Salons
    structure = {
        "📌 INFORMATIONS": ["reglement", "annonces", "bienvenue", "faq"],
        "💬 ZONE HRP": ["chat-hrp", "commandes-bot", "suggestions"],
        "🎭 ZONE RP": ["twitter-rp", "leaks-rp", "lifeinvader"],
        "🎫 SUPPORT & SERVICES": ["tickets"]
    }

    general_chan = None
    welcome_chan = None

    for cat_name, channels in structure.items():
        category = discord.utils.get(guild.categories, name=cat_name)
        if not category:
            category = await guild.create_category(cat_name)

        for ch_name in channels:
            ch = discord.utils.get(category.text_channels, name=ch_name)
            if not ch:
                ch = await guild.create_text_channel(name=ch_name, category=category)
            if ch_name == "chat-hrp" and not general_chan:
                general_chan = ch
            if ch_name == "bienvenue" and not welcome_chan:
                welcome_chan = ch

    # Sauvegarde dans la base de données
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            INSERT INTO guild_config (guild_id, general_channel, welcome_channel, staff_role)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                general_channel=excluded.general_channel,
                welcome_channel=excluded.welcome_channel,
                staff_role=excluded.staff_role
        """, (guild.id, general_chan.id if general_chan else None, welcome_chan.id if welcome_chan else None, created_roles["Staff / Admin"].id))
        await db.commit()

    # Message de bienvenue automatique post-création
    target = welcome_chan or general_chan
    if target:
        embed = discord.Embed(
            title="🎉 Serveur ORAN RP Prêt !",
            description="L'architecture RP a été générée avec succès par **Lia**.\nUtilisez `/admin` pour personnaliser la suite !",
            color=discord.Color.green()
        )
        await target.send(embed=embed)

    await interaction.followup.send("✅ Serveur RP généré et configuré avec succès !", ephemeral=True)

# 2. /admin
@bot.tree.command(name="admin", description="Ouvrir le panneau d'administration central")
@app_commands.checks.has_permissions(administrator=True)
async def admin_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Panneau de Contrôle Administrateur — ORAN RP",
        description="Gérez les tickets, candidatures, annonces, modération et configurations du serveur.",
        color=discord.Color.dark_purple()
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, view=AdminDashboardView(), ephemeral=True)

# 3. /supprimer-server
@bot.tree.command(name="supprimer-server", description="Réinitialiser entièrement la configuration ORAN RP")
async def supprimer_server(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Seul le propriétaire du serveur peut exécuter cette commande.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ ATTENTION — RÉINITIALISATION TOTALE",
        description="Cette action va effacer la configuration enregistrée par Lia dans la base de données.\nÊtes-vous absolument sûr ?",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, view=DeleteServerConfirmView(), ephemeral=True)

# 4. /jeux
@bot.tree.command(name="jeux", description="Afficher l'état du serveur RP, les statistiques et le Staff")
async def jeux(interaction: discord.Interaction):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT game_cfx_id, game_name, game_link, staff_role FROM guild_config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()

    cfx_id, game_name, game_link, staff_role_id = row if row else (None, "ORAN RP", None, None)
    
    online_players = "Non connecté (API)"
    max_players = "64"

    # Récupération API FiveM Réelle sans invention
    if cfx_id:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://servers-frontend.fivem.net/api/servers/single/{cfx_id}", timeout=3) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        online_players = str(data['Data']['clients'])
                        max_players = str(data['Data']['sv_maxclients'])
        except Exception:
            online_players = "Indisponible"

    embed = discord.Embed(title=f"🎮 Statut — {game_name}", color=discord.Color.blue())
    embed.add_field(name="Joueurs en ligne", value=f"🟢 **{online_players} / {max_players}**", inline=True)
    embed.add_field(name="Lien / Connexion", value=game_link or "Non configuré", inline=True)
    
    # Propriétaire & Staff
    owner = interaction.guild.owner
    embed.add_field(name="Fondateur", value=owner.mention if owner else "Inconnu", inline=False)
    
    if staff_role_id:
        staff_role = interaction.guild.get_role(staff_role_id)
        if staff_role:
            members = [m.mention for m in staff_role.members[:10]]
            embed.add_field(name="Membres du Staff", value=", ".join(members) if members else "Aucun membre", inline=False)

    await interaction.response.send_message(embed=embed)

# 5. /annonce
@bot.tree.command(name="annonce", description="Publier ou programmer une annonce")
@app_commands.checks.has_permissions(manage_messages=True)
async def annonce(interaction: discord.Interaction, salon: discord.TextChannel, titre: str, description: str, couleur_hex: str = "#00FF88", image_url: str = None, delai_minutes: int = 0):
    try:
        col = int(couleur_hex.replace("#", ""), 16)
    except ValueError:
        col = discord.Color.blue().value

    embed = discord.Embed(title=titre, description=description, color=col)
    if image_url: embed.set_image(url=image_url)
    embed.set_footer(text=f"Annonce Officielle • {interaction.guild.name}")

    if delai_minutes > 0:
        await interaction.response.send_message(f"⏳ Annonce programmée pour envoi dans {delai_minutes} minutes.", ephemeral=True)
        await asyncio.sleep(delai_minutes * 60)
        await salon.send(embed=embed)
    else:
        await salon.send(embed=embed)
        await interaction.response.send_message("✅ Annonce envoyée !", ephemeral=True)

# 6. /youtube-ajouter
@bot.tree.command(name="youtube-ajouter", description="Ajouter une chaîne YouTube à suivre")
@app_commands.checks.has_permissions(administrator=True)
async def youtube_add(interaction: discord.Interaction, channel_id: str, salon_destination: discord.TextChannel):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            INSERT INTO social_feeds (guild_id, platform, channel_identifier, target_channel_id)
            VALUES (?, 'youtube', ?, ?)
        """, (interaction.guild.id, channel_id, salon_destination.id))
        await db.commit()
    await interaction.response.send_message(f"✅ Flux YouTube enregistré pour le salon {salon_destination.mention} !", ephemeral=True)

# 7. Commandes Utilitaires & Modération
@bot.tree.command(name="ticket", description="Poser le panneau de tickets")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫 Support & Candidatures", description="Sélectionnez l'option désirée dans le menu ci-dessous :", color=discord.Color.red())
    view = ui.View()
    view.add_item(TicketSelectMenu())
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="clear", description="Supprimer un nombre de messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, nombre: int):
    deleted = await interaction.channel.purge(limit=nombre)
    await interaction.response.send_message(f"🗑️ {len(deleted)} messages supprimés.", ephemeral=True)

@bot.tree.command(name="warn", description="Avertir un joueur")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, membre: discord.Member, raison: str):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)", (interaction.guild.id, membre.id, interaction.user.id, raison))
        await db.commit()
    await interaction.response.send_message(f"⚠️ {membre.mention} a été averti pour : **{raison}**")

@bot.tree.command(name="ban", description="Bannir un utilisateur")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune"):
    await membre.ban(reason=raison)
    await interaction.response.send_message(f"🔨 {membre.mention} a été banni du serveur.")

@bot.tree.command(name="backup", description="Télécharger une sauvegarde JSON")
@app_commands.checks.has_permissions(administrator=True)
async def backup(interaction: discord.Interaction):
    guild = interaction.guild
    data = {
        "server_name": guild.name,
        "roles": [r.name for r in guild.roles],
        "channels": [c.name for c in guild.channels]
    }
    file_bytes = json.dumps(data, indent=4).encode("utf-8")
    await interaction.response.send_message("💾 Sauvegarde générée :", file=discord.File(io.BytesIO(file_bytes), filename="backup.json"), ephemeral=True)


# ==========================================
# VERIFICATEUR SOCIAL AUTOMATIQUE
# ==========================================

@tasks.loop(minutes=5)
async def check_social_feeds():
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT id, guild_id, channel_identifier, target_channel_id, last_post_id FROM social_feeds WHERE platform='youtube'") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                feed_id, guild_id, chan_id, target_chan_id, last_post = row
                url = f"https://www.youtube.com/feeds/videos.xml?channel_id={chan_id}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            feed = feedparser.parse(await resp.text())
                            if feed.entries:
                                latest = feed.entries[0]
                                if latest.id != last_post:
                                    guild = bot.get_guild(guild_id)
                                    if guild:
                                        target = guild.get_channel(target_chan_id)
                                        if target:
                                            await target.send(f"🔴 **Nouvelle vidéo YouTube !**\n{latest.title}\n{latest.link}")
                                    await db.execute("UPDATE social_feeds SET last_post_id = ? WHERE id = ?", (latest.id, feed_id))
                                    await db.commit()

# Exécution du Bot
if __name__ == "__main__":
    if not TOKEN:
        print("CRITICAL: DISCORD_TOKEN manquant dans .env")
    else:
        bot.run(TOKEN)
