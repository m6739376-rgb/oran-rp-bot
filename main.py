import os
import io
import json
import random
import asyncio
import logging
import aiosqlite
import discord
from discord import app_commands, ui
from discord.ext import commands
from dotenv import load_dotenv

# Chargement du token via .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO)

# ==========================================
# INTERFACES INTERACTIVES (VIEWS, MODALS)
# ==========================================

# Formulaire Assistant de Création
class ServerBuilderModal(ui.Modal, title="Configuration du Serveur RP"):
    roles_count = ui.TextInput(label="Combien de rôles ?", placeholder="Ex: 5", default="3")
    roles_names = ui.TextInput(label="Noms des rôles (séparés par des virgules)", placeholder="Citoyen, Police, EMS", style=discord.TextStyle.paragraph)
    channels_names = ui.TextInput(label="Noms des salons", placeholder="general, hrp, annonce-rp", style=discord.TextStyle.paragraph)
    categories = ui.TextInput(label="Catégories", placeholder="INFORMATION, HRP, RP", style=discord.TextStyle.paragraph)
    structure = ui.TextInput(label="Structure/Thème", placeholder="Serious RP, Semi-RP...", default="Serious RP")

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚡ Aperçu de la Configuration Serveur",
            color=discord.Color.gold(),
            description=f"**Structure :** {self.structure.value}"
        )
        embed.add_field(name="Rôles", value=f"**Nombre:** {self.roles_count.value}\n**Liste:** {self.roles_names.value}", inline=False)
        embed.add_field(name="Salons", value=self.channels_names.value, inline=False)
        embed.add_field(name="Catégories", value=self.categories.value, inline=False)

        view = ConfirmBuildView(self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmBuildView(ui.View):
    def __init__(self, data: ServerBuilderModal):
        super().__init__(timeout=180)
        self.data = data

    @ui.button(label="Confirmer et Créer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("🛠️ Création de la structure en cours...", ephemeral=True)
        guild = interaction.guild

        role_list = [r.strip() for r in self.data.roles_names.value.split(",") if r.strip()]
        for r_name in role_list:
            await guild.create_role(name=r_name)

        cat_list = [c.strip() for c in self.data.categories.value.split(",") if c.strip()]
        chan_list = [ch.strip() for ch in self.data.channels_names.value.split(",") if ch.strip()]

        for cat_name in cat_list:
            category = await guild.create_category(cat_name)
            for ch_name in chan_list:
                await guild.create_text_channel(name=ch_name, category=category)

        await interaction.followup.send("✅ Structure du serveur créée avec succès !", ephemeral=True)

    @ui.button(label="Annuler", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("❌ Opération annulée.", ephemeral=True)

# Panneau de Contrôle Ticket
class TicketControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("🔒 Fermeture et génération du transcript...", ephemeral=True)
        
        messages = [msg async for msg in interaction.channel.history(limit=500, oldest_first=True)]
        transcript_text = f"--- TRANSCRIPT TICKET {interaction.channel.name} ---\n\n"
        for msg in messages:
            transcript_text += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.content}\n"

        file = discord.File(io.BytesIO(transcript_text.encode('utf-8')), filename=f"transcript-{interaction.channel.name}.txt")

        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT ticket_logs FROM guild_config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    log_chan = interaction.guild.get_channel(row[0])
                    if log_chan:
                        await log_chan.send(content=f"Transcript du ticket **{interaction.channel.name}** fermé par {interaction.user.mention}:", file=file)

        await interaction.channel.delete()

# Menu Déroulant Tickets
class TicketLauncherSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Basique", description="Besoin d'aide générale", emoji="🎫", value="basic"),
            discord.SelectOption(label="Candidature RP", description="Déposer une candidature", emoji="📝", value="candidature"),
            discord.SelectOption(label="Ticket Personnalisé", description="Autre demande spécifique", emoji="⚙️", value="custom")
        ]
        super().__init__(placeholder="Choisissez le type de ticket...", min_values=1, max_values=1, options=options, custom_id="ticket_select_launcher")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        ticket_type = self.values[0]

        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT ticket_category FROM guild_config WHERE guild_id = ?", (guild.id,)) as cursor:
                row = await cursor.fetchone()
                category = guild.get_channel(row[0]) if row and row[0] else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{ticket_type}-{user.name}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title=f"🎫 Ticket - {ticket_type.capitalize()}",
            description=f"Bonjour {user.mention}, posez votre question ici. Un membre du Staff vous répondra rapidement.",
            color=discord.Color.blue()
        )

        await channel.send(embed=embed, view=TicketControlView())
        await interaction.response.send_message(f"✅ Ticket ouvert : {channel.mention}", ephemeral=True)

# Système de Suggestions
class SuggestionView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.upvotes = 0
        self.downvotes = 0

    @ui.button(label="Pour (0)", style=discord.ButtonStyle.success, emoji="👍", custom_id="sug_up")
    async def upvote(self, interaction: discord.Interaction, button: ui.Button):
        self.upvotes += 1
        button.label = f"Pour ({self.upvotes})"
        await interaction.response.edit_message(view=self)

    @ui.button(label="Contre (0)", style=discord.ButtonStyle.danger, emoji="👎", custom_id="sug_down")
    async def downvote(self, interaction: discord.Interaction, button: ui.Button):
        self.downvotes += 1
        button.label = f"Contre ({self.downvotes})"
        await interaction.response.edit_message(view=self)

# Formulaire d'Annonce
class AnnouncementModal(ui.Modal, title="Créer une Annonce Pro"):
    title_input = ui.TextInput(label="Titre de l'annonce", placeholder="Titre...")
    desc_input = ui.TextInput(label="Contenu", style=discord.TextStyle.paragraph, placeholder="Contenu de l'annonce...")
    color_input = ui.TextInput(label="Couleur Hex (#FF0000)", default="#00FF88", required=False)
    image_input = ui.TextInput(label="URL Image (Facultatif)", required=False)

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color_int = int(self.color_input.value.replace("#", ""), 16)
        except ValueError:
            color_int = discord.Color.red().value

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.desc_input.value,
            color=color_int
        )
        embed.set_footer(text=f"ORAN RP • Par {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        if self.image_input.value:
            embed.set_image(url=self.image_input.value)

        await self.channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Annonce publiée dans {self.channel.mention} !", ephemeral=True)

# Vérification Automatique
class VerificationView(ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @ui.button(label="Accepter le Règlement & Se Vérifier", style=discord.ButtonStyle.success, emoji="✅", custom_id="verify_btn")
    async def verify(self, interaction: discord.Interaction, button: ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if role:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("✅ Vous avez été vérifié avec succès !", ephemeral=True)


# ==========================================
# CLASSE PRINCIPALE DU BOT
# ==========================================

class OranRPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.init_db()
        await self.tree.sync()
        print("✅ Commandes Slash synchronisées !")

    async def init_db(self):
        async with aiosqlite.connect("database.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel INTEGER,
                    welcome_channel INTEGER,
                    welcome_message TEXT,
                    auto_role INTEGER,
                    ticket_category INTEGER,
                    ticket_logs INTEGER,
                    maintenance BOOLEAN DEFAULT 0
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
            await db.commit()

bot = OranRPBot()

# Event au démarrage
@bot.event
async def on_ready():
    print(f" Connecté avec succès : {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="ORAN RP | /aide"))

# Event Nouveau Membre (Bienvenue & Auto-Role)
@bot.event
async def on_member_join(member):
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT welcome_channel, welcome_message, auto_role FROM guild_config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                w_chan_id, w_msg, a_role_id = row
                if a_role_id:
                    role = member.guild.get_role(a_role_id)
                    if role:
                        await member.add_roles(role)
                if w_chan_id:
                    chan = member.guild.get_channel(w_chan_id)
                    if chan:
                        text = w_msg.format(user=member.mention) if w_msg else f"Bienvenue {member.mention} sur **ORAN RP** !"
                        await chan.send(text)

# Event Détection Phrase Naturelle ("Oran RP")
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # Détection mode maintenance
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT maintenance FROM guild_config WHERE guild_id = ?", (message.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] and not message.author.guild_permissions.administrator:
                return

    # Commande naturelle Oran RP
    if message.content.lower().startswith("oran rp"):
        content = message.content.lower()
        if "fais-moi un serveur" in content or "crée un serveur" in content:
            if not message.author.guild_permissions.administrator:
                await message.channel.send("❌ Vous devez être administrateur pour cette action.")
                return

            view = ui.View()
            btn = ui.Button(label="Lancer l'assistant de création", style=discord.ButtonStyle.primary, emoji="🚀")
            
            async def btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(ServerBuilderModal())

            btn.callback = btn_callback
            view.add_item(btn)

            await message.channel.send(
                f"Bonjour {message.author.mention}, cliquez ci-dessous pour configurer votre serveur ORAN RP.",
                view=view
            )
            return

    await bot.process_commands(message)


# ==========================================
# COMMANDES SLASH (SLASH COMMANDS)
# ==========================================

# /aide
@bot.tree.command(name="aide", description="Affiche la liste des commandes")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=" Menu d'Aide - ORAN RP",
        description="Voici les commandes disponibles pour votre serveur :",
        color=discord.Color.red()
    )
    embed.add_field(name="🤖 Assistant", value="Dites `Oran RP fais-moi un serveur` dans le chat.", inline=False)
    embed.add_field(name="🛡️ Modération", value="`/clear`, `/lock`, `/unlock`, `/slowmode`, `/warn`, `/kick`, `/ban`, `/unban`", inline=False)
    embed.add_field(name="⚙️ Admin & Config", value="`/config`, `/logs`, `/bienvenue`, `/auto-role`, `/verification`, `/maintenance`, `/backup`", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket` - Déployer le panneau de tickets", inline=False)
    embed.add_field(name="📢 Utilitaires", value="`/annonce`, `/reglement`, `/sondage`, `/suggestion`, `/giveaway`, `/userinfo`, `/serverinfo`", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# /ticket
@bot.tree.command(name="ticket", description="Afficher le panneau de tickets")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=" Support & Candidatures - ORAN RP",
        description="Sélectionnez l'option désirée dans le menu ci-dessous pour ouvrir un ticket privé.",
        color=discord.Color.dark_red()
    )
    view = ui.View()
    view.add_item(TicketLauncherSelect())
    await interaction.response.send_message(embed=embed, view=view)

# /annonce
@bot.tree.command(name="annonce", description="Créer une annonce professionnelle")
@app_commands.checks.has_permissions(manage_messages=True)
async def create_announcement(interaction: discord.Interaction, salon: discord.TextChannel):
    await interaction.response.send_modal(AnnouncementModal(channel=salon))

# /clear
@bot.tree.command(name="clear", description="Supprime un nombre de messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, nombre: int):
    deleted = await interaction.channel.purge(limit=nombre)
    await interaction.response.send_message(f"🗑️ {len(deleted)} messages supprimés.", ephemeral=True)

# /lock
@bot.tree.command(name="lock", description="Verrouille le salon")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Salon verrouillé.")

# /unlock
@bot.tree.command(name="unlock", description="Déverrouille le salon")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Salon déverrouillé.")

# /slowmode
@bot.tree.command(name="slowmode", description="Configure le mode lent en secondes")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, secondes: int):
    await interaction.channel.edit(slowmode_delay=secondes)
    await interaction.response.send_message(f"⏱️ Mode lent réglé sur {secondes}s.")

# /warn
@bot.tree.command(name="warn", description="Avertir un membre")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, membre: discord.Member, raison: str):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                         (interaction.guild.id, membre.id, interaction.user.id, raison))
        await db.commit()
    await interaction.response.send_message(f"⚠️ {membre.mention} a reçu un avertissement pour : **{raison}**")

# /kick
@bot.tree.command(name="kick", description="Expulser un membre")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.kick(reason=raison)
    await interaction.response.send_message(f"👞 {membre.mention} a été expulsé.")

# /ban
@bot.tree.command(name="ban", description="Bannir un membre")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.ban(reason=raison)
    await interaction.response.send_message(f"🔨 {membre.mention} a été banni.")

# /unban
@bot.tree.command(name="unban", description="Débannir un membre via son ID")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    user = await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(f"✅ {user.name} a été débanni.")

# /auto-role
@bot.tree.command(name="auto-role", description="Définir un rôle automatique aux nouveaux")
@app_commands.checks.has_permissions(administrator=True)
async def autorole(interaction: discord.Interaction, role: discord.Role):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO guild_config (guild_id, auto_role) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET auto_role=excluded.auto_role",
                         (interaction.guild.id, role.id))
        await db.commit()
    await interaction.response.send_message(f"✅ Rôle automatique défini sur {role.mention}")

# /verification
@bot.tree.command(name="verification", description="Installer le système de vérification")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verification(interaction: discord.Interaction, role: discord.Role):
    embed = discord.Embed(
        title="🔒 Vérification - ORAN RP",
        description="Cliquez ci-dessous pour valider le règlement et accéder au serveur.",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=VerificationView(role.id))
    await interaction.response.send_message("✅ Système de vérification placé !", ephemeral=True)

# /maintenance
@bot.tree.command(name="maintenance", description="Activer ou désactiver le mode maintenance")
@app_commands.checks.has_permissions(administrator=True)
async def maintenance(interaction: discord.Interaction, etat: bool):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT INTO guild_config (guild_id, maintenance) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET maintenance=excluded.maintenance",
                         (interaction.guild.id, etat))
        await db.commit()
    await interaction.response.send_message(f"⚙️ Maintenance : **{'Activée 🔴' if etat else 'Désactivée 🟢'}**")

# /suggestion
@bot.tree.command(name="suggestion", description="Proposer une idée pour le serveur")
async def suggestion(interaction: discord.Interaction, texte: str):
    embed = discord.Embed(
        title="💡 Nouvelle Suggestion RP",
        description=texte,
        color=discord.Color.gold()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message("✅ Votre suggestion a été transmise !", ephemeral=True)
    await interaction.channel.send(embed=embed, view=SuggestionView())

# /giveaway
@bot.tree.command(name="giveaway", description="Lancer un concours")
@app_commands.checks.has_permissions(administrator=True)
async def giveaway(interaction: discord.Interaction, duree_secondes: int, recompense: str):
    embed = discord.Embed(
        title="🎉 CONCOURS ORAN RP",
        description=f"**Gain :** {recompense}\nRéagissez avec 🎉 pour participer !\n**Fin dans :** {duree_secondes}s",
        color=discord.Color.purple()
    )
    await interaction.response.send_message("Concours démarré !", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")

    await asyncio.sleep(duree_secondes)

    msg = await interaction.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    users = [u async for u in reaction.users() if not u.bot]

    if users:
        winner = random.choice(users)
        await interaction.channel.send(f"🎊 Félicitations {winner.mention}, tu as gagné : **{recompense}** !")
    else:
        await interaction.channel.send("❌ Aucun participant pour ce concours.")

# /backup
@bot.tree.command(name="backup", description="Télécharger une sauvegarde JSON de la structure")
@app_commands.checks.has_permissions(administrator=True)
async def backup(interaction: discord.Interaction):
    guild = interaction.guild
    data = {
        "name": guild.name,
        "roles": [r.name for r in guild.roles if not r.is_default()],
        "categories": [c.name for c in guild.categories],
        "channels": [c.name for c in guild.channels]
    }
    json_bytes = json.dumps(data, indent=4, ensure_ascii=False).encode('utf-8')
    file = discord.File(io.BytesIO(json_bytes), filename=f"backup-{guild.id}.json")
    await interaction.response.send_message("💾 Sauvegarde de la structure :", file=file, ephemeral=True)

# Lancement
if __name__ == "__main__":
    if not TOKEN:
        print("Erreur: DISCORD_TOKEN manquant dans le fichier .env")
    else:
        bot.run(TOKEN)
