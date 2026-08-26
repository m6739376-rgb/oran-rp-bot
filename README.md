# oran-rp-bot
🇩🇿 Bot Discord complet pour ORAN RP avec IA Lia - Gestion de candidatures, groupes, métiers
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_loadenv

# Chargement des variables d'environnement
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuration des Intentions
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class OranBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Synchronisation des commandes slash avec Discord
        await self.tree.sync()
        print("✅ Commandes Slash synchronisées avec succès !")

bot = OranBot()

# --- VÉRIFICATION DES PERMISSIONS ---
def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

# --- TEMPLATES DE CRÉATION DE SERVEUR ---
def get_template(description: str):
    desc = description.lower()
    if any(k in desc for k in ["gta", "fivem", "erlc", "roblox"]):
        return {
            "roles": [
                {"name": "👑┃Fondateur", "color": discord.Color.red()},
                {"name": "🛡️┃Staff", "color": discord.Color.blue()},
                {"name": "🚓┃Police - Direction", "color": discord.Color.dark_blue()},
                {"name": "🚓┃Police - Officier", "color": discord.Color.teal()},
                {"name": "🚒┃EMS / Pompiers", "color": discord.Color.brand_red()},
                {"name": "💼┃Entreprise", "color": discord.Color.gold()},
                {"name": "🔫┃Organisation / Gang", "color": discord.Color.purple()},
                {"name": "👤┃Citoyen", "color": discord.Color.light_grey()}
            ],
            "categories": [
                {
                    "name": "📁 INFORMATIONS",
                    "channels": [
                        ("📜・règlement", discord.ChannelType.text),
                        ("📢・annonces", discord.ChannelType.text),
                        ("👋・bienvenue", discord.ChannelType.text),
                        ("📌・informations", discord.ChannelType.text)
                    ]
                },
                {
                    "name": "📁 COMMUNAUTÉ",
                    "channels": [
                        ("💬・général", discord.ChannelType.text),
                        ("🎮・discussion", discord.ChannelType.text),
                        ("📸・screenshots", discord.ChannelType.text),
                        ("🔊・Vocal Général", discord.ChannelType.voice)
                    ]
                },
                {
                    "name": "📁 ESPACE RP",
                    "channels": [
                        ("🚓・police", discord.ChannelType.text),
                        ("🚒・pompiers-ems", discord.ChannelType.text),
                        ("💼・entreprises", discord.ChannelType.text),
                        ("🔫・illégal", discord.ChannelType.text)
                    ]
                },
                {
                    "name": "📁 SUPPORT",
                    "channels": [
                        ("🎫・tickets", discord.ChannelType.text)
                    ]
                }
            ]
        }
    else:
        return {
            "roles": [
                {"name": "👑┃Staff", "color": discord.Color.red()},
                {"name": "🎭┃Joueur RP", "color": discord.Color.green()}
            ],
            "categories": [
                {
                    "name": "📁 INFORMATIONS",
                    "channels": [
                        ("📜・règlement", discord.ChannelType.text),
                        ("📢・annonces", discord.ChannelType.text),
                        ("👋・bienvenue", discord.ChannelType.text)
                    ]
                },
                {
                    "name": "📁 DISCUSSION",
                    "channels": [
                        ("💬・général", discord.ChannelType.text),
                        ("🔊・Vocal", discord.ChannelType.voice)
                    ]
                },
                {
                    "name": "📁 SUPPORT",
                    "channels": [
                        ("🎫・tickets", discord.ChannelType.text)
                    ]
                }
            ]
        }

# --- INTERFACES BOUTONS ---

class ConfirmBuildView(discord.ui.View):
    def __init__(self, template, author):
        super().__init__(timeout=60)
        self.template = template
        self.author = author

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.green, custom_id="confirm_build")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Seul l'auteur de la commande peut utiliser ce bouton.", ephemeral=True)
        
        await interaction.response.edit_message(content="⚙️ Déploiement du serveur en cours...", embed=None, view=None)
        guild = interaction.guild

        try:
            # 1. Création des rôles
            for r in self.template["roles"]:
                await guild.create_role(name=r["name"], color=r["color"], reason="Configuration ORAN RP")

            # 2. Création des salons
            for cat in self.template["categories"]:
                category = await guild.create_category(name=cat["name"])
                for name, c_type in cat["channels"]:
                    if c_type == discord.ChannelType.text:
                        await guild.create_text_channel(name=name, category=category)
                    elif c_type == discord.ChannelType.voice:
                        await guild.create_voice_channel(name=name, category=category)

            await interaction.followup.send("✅ La structure du serveur a été déployée avec succès !")
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur lors du déploiement : {e}")

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.red, custom_id="cancel_build")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Action non autorisée.", ephemeral=True)
        await interaction.response.edit_message(content="❌ Opération annulée.", embed=None, view=None)

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Fermeture du ticket dans 5 secondes...")
        import asyncio
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            reason="Ticket support"
        )
        await channel.send(
            content=f"Bienvenue {interaction.user.mention}, un membre du staff va s'occuper de vous.",
            view=TicketCloseView()
        )
        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)

# --- COMMANDES SLASH ---

@bot.tree.command(name="oran-rp", description="Assistance pour le projet ORAN RP")
async def oran_rp(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="🤖 Assistant ORAN RP", color=discord.Color.gold())
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Réponse", value="Bienvenue sur le système ORAN RP ! Utilisez `/creer-serveur` pour initialiser la structure.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="creer-serveur", description="Création guidée d'un serveur RP")
async def creer_serveur(interaction: discord.Interaction, description: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)

    template = get_template(description)
    roles_list = ", ".join([r["name"] for r in template["roles"]])
    cats_list = ", ".join([c["name"] for c in template["categories"]])

    embed = discord.Embed(
        title="📋 Aperçu de la configuration",
        description=f"**Rôles :** {roles_list}\n\n**Catégories :** {cats_list}",
        color=discord.Color.green()
    )
    embed.set_footer(text="Confirmez-vous la création automatique ?")

    view = ConfirmBuildView(template=template, author=interaction.user)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="ticket", description="Configure le panneau de tickets")
async def ticket(interaction: discord.Interaction, salon: discord.TextChannel, titre: str, description: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)

    embed = discord.Embed(title=titre, description=description, color=discord.Color.blue())
    await salon.send(embed=embed, view=TicketOpenView())
    await interaction.response.send_message("Panneau de tickets déployé !", ephemeral=True)

@bot.tree.command(name="annonce", description="Créer une annonce professionnelle")
async def annonce(interaction: discord.Interaction, salon: discord.TextChannel, titre: str, description: str, image: str = None):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)

    embed = discord.Embed(title=titre, description=description, color=discord.Color.green())
    embed.set_footer(text=f"Publié par {interaction.user.display_name}")
    if image:
        embed.set_image(url=image)

    await salon.send(embed=embed)
    await interaction.response.send_message("Annonce envoyée !", ephemeral=True)

@bot.tree.command(name="aide", description="Affiche les commandes du bot")
async def aide(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Aide - ORAN RP Bot", color=discord.Color.blue())
    embed.add_field(name="/oran-rp", value="Pose une question à l'assistant ORAN RP.", inline=False)
    embed.add_field(name="/creer-serveur", value="Génère la structure du serveur selon votre description.", inline=False)
    embed.add_field(name="/ticket", value="Installe le module de tickets sur un salon.", inline=False)
    embed.add_field(name="/annonce", value="Envoie une annonce sous forme d'embed.", inline=False)
    await interaction.response.send_message(embed=embed)

# --- LANCEMENT DU BOT ---
@bot.event
async def on_ready():
    print(f"🤖 Bot démarré avec le pseudo : {bot.user.name}")

if __name__ == "__main__":
    bot.run(TOKEN)
