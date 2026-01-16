"""Teams Webhook integration for sending Adaptive Cards to channels."""
import aiohttp
from typing import Optional, List, Dict, Any
from navconfig.logging import logging


class TeamsWebhook:
    """Sends Adaptive Card notifications to MS Teams channels via incoming webhooks.
    
    Usage:
        webhook = TeamsWebhook(webhook_url="https://outlook.office.com/webhook/...")
        await webhook.send_adaptive_card(card_payload)
    """
    
    def __init__(self, webhook_url: str):
        """Initialize TeamsWebhook with the webhook URL.
        
        Args:
            webhook_url: The incoming webhook URL from MS Teams channel connector.
        """
        self.webhook_url = webhook_url
        self.logger = logging.getLogger('rewards.teams_webhook')
    
    async def send_adaptive_card(self, card: Dict[str, Any]) -> bool:
        """Send an Adaptive Card to the Teams channel.
        
        Args:
            card: Adaptive Card JSON payload (dict).
            
        Returns:
            bool: True if successful, False otherwise.
        """
        # Wrap Adaptive Card in the required Teams webhook format
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card
                }
            ]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        self.logger.info(
                            "Teams webhook notification sent successfully"
                        )
                        return True
                    else:
                        text = await response.text()
                        self.logger.error(
                            f"Teams webhook failed: {response.status} - {text}"
                        )
                        return False
        except aiohttp.ClientError as e:
            self.logger.error(f"Teams webhook connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Teams webhook unexpected error: {e}")
            return False
    
    async def send_birthday_notification(
        self,
        users: List[Dict[str, Any]],
        reward_name: str = "Birthday Badge",
        reward_icon: Optional[str] = None
    ) -> bool:
        """Send a birthday celebration notification for multiple users.
        
        Args:
            users: List of user dicts with 'display_name', 'email' keys.
            reward_name: Name of the reward/badge.
            reward_icon: Optional URL to reward icon.
            
        Returns:
            bool: True if successful.
        """
        if not users:
            self.logger.info("No users to notify for birthday")
            return True
        
        # Build user mention list
        user_items = []
        for user in users:
            name = user.get('display_name', user.get('email', 'Unknown'))
            user_items.append({
                "type": "TextBlock",
                "text": f"🎂 **{name}**",
                "wrap": True
            })
        
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "🎉 Birthday Celebrations Today! 🎉",
                    "weight": "Bolder",
                    "size": "Large",
                    "horizontalAlignment": "Center",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": f"Please join us in wishing a Happy Birthday to our team members:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Container",
                    "items": user_items,
                    "style": "emphasis",
                    "bleed": True,
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": f"🏆 They've been awarded the **{reward_name}**!",
                    "wrap": True,
                    "spacing": "Medium",
                    "horizontalAlignment": "Center"
                }
            ]
        }
        
        # Add icon if provided
        if reward_icon:
            card["body"].insert(0, {
                "type": "Image",
                "url": reward_icon,
                "size": "Medium",
                "horizontalAlignment": "Center"
            })
        
        return await self.send_adaptive_card(card)
    
    async def send_anniversary_notification(
        self,
        users: List[Dict[str, Any]],
        reward_name: str = "Work Anniversary",
        reward_icon: Optional[str] = None
    ) -> bool:
        """Send a work anniversary celebration notification for multiple users.
        
        Args:
            users: List of user dicts with 'display_name', 'email', 'years_employed' keys.
            reward_name: Name of the reward/badge.
            reward_icon: Optional URL to reward icon.
            
        Returns:
            bool: True if successful.
        """
        if not users:
            self.logger.info("No users to notify for anniversary")
            return True
        
        # Build user mention list with years
        user_items = []
        for user in users:
            name = user.get('display_name', user.get('email', 'Unknown'))
            years = user.get('years_employed', '?')
            user_items.append({
                "type": "TextBlock",
                "text": f"🎊 **{name}** - {years} year(s)!",
                "wrap": True
            })
        
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "🏆 Work Anniversaries Today! 🏆",
                    "weight": "Bolder",
                    "size": "Large",
                    "horizontalAlignment": "Center",
                    "color": "Accent"
                },
                {
                    "type": "TextBlock",
                    "text": "Congratulations to our team members celebrating their work anniversaries:",
                    "wrap": True,
                    "spacing": "Medium"
                },
                {
                    "type": "Container",
                    "items": user_items,
                    "style": "emphasis",
                    "bleed": True,
                    "spacing": "Medium"
                },
                {
                    "type": "TextBlock",
                    "text": f"🎉 They've been awarded the **{reward_name}**!",
                    "wrap": True,
                    "spacing": "Medium",
                    "horizontalAlignment": "Center"
                }
            ]
        }
        
        # Add icon if provided
        if reward_icon:
            card["body"].insert(0, {
                "type": "Image",
                "url": reward_icon,
                "size": "Medium",
                "horizontalAlignment": "Center"
            })
        
        return await self.send_adaptive_card(card)
