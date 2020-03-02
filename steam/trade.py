from datetime import datetime

from .enums import Game, ETradeOfferState
from .errors import ClientException


class TradeOffer:
    """Represents a Trade offer from a User.

    Attributes
    -------------
    partner: class:`~steam.User`
        The trade offer partner.
    items_to_give: List[`Item`]
        A list of items to give to the trade partner.
    items_to_receive: List[`Item`]
        A list of items to receive from the.
    state:
        The offer state of the trade for the possible types see
        :class:`~enums.ETradeOfferState`.
    message: :class:`str`
        The message included with the trade offer.
    is_our_offer: :class:`bool`
        Whether the offer was created by the ClientUser.
    id: :class:`int`
        The trade offer id of the trade.
    expires: :class:`datetime.datetime`
        The time at which the trade automatically expires.
    escrow: Optional[class:`datetime.datetime`]
        The time at which the escrow will end. Can be None
        if there is no escrow on the trade.
    """

    __slots__ = ('partner', 'message', 'state', 'is_our_offer', 'id',
                 'expires', 'escrow', 'items_to_give', 'items_to_receive',
                 '_state', '_data')

    def __init__(self, state, data, partner):
        self._state = state
        self.partner = partner
        self._update(data)

    def __repr__(self):
        attrs = (
            'id', 'partner'
        )
        resolved = [f'{attr}={repr(getattr(self, attr))}' for attr in attrs]
        return f"<TradeOffer {' '.join(resolved)}>"

    def _update(self, data):
        self.message = data['message'] or None
        self.is_our_offer = data['is_our_offer']
        self.id = int(data['tradeofferid'])
        self.expires = datetime.utcfromtimestamp(data['expiration_time'])
        self.escrow = datetime.utcfromtimestamp(data['escrow_end_date']) if data['escrow_end_date'] != 0 else None
        self.state = ETradeOfferState(data.get('trade_offer_state', 1))
        self._data = data

    async def _async__init__(self):
        if self.partner is None:  # not great cause this can be your account sometimes
            self.partner = await self._state.client.fetch_user(self._data['accountid_other'])
            print(self.partner)
        self.items_to_give = await self.fetch_items(
            user_id64=self._state.client.user.id64,
            assets=self._data['items_to_receive']
        ) if 'items_to_receive' in self._data.keys() else []

        self.items_to_receive = await self.fetch_items(
            user_id64=self.partner.id64,
            assets=self._data['items_to_give']
        ) if 'items_to_give' in self._data.keys() else []

    async def update(self):
        data = await self._state.http.fetch_trade(self.id)
        await self._async__init__()
        self._update(data)
        return self

    async def accept(self):
        if self.state != ETradeOfferState.Active:
            raise ClientException('This trade is not active')
        await self._state.http.accept_trade(self.id)
        self.state = ETradeOfferState.Accepted
        self._state.dispatch('trade_accept', self)

    async def decline(self):
        if self.state != ETradeOfferState.Active and self.state != ETradeOfferState.ConfirmationNeed:
            raise ClientException('This trade is not active')
        elif self.is_our_offer:
            raise ClientException('You cannot decline an offer the ClientUser has made')
        await self._state.http.decline_user_trade(self.id)
        self.state = ETradeOfferState.Declined
        self._state.dispatch('trade_decline', self)

    async def cancel(self):
        if self.state != ETradeOfferState.Active and self.state != ETradeOfferState.ConfirmationNeed:
            raise ClientException('This trade is not active')
        if not self.is_our_offer:
            raise ClientException("Offer wasn't created by the ClientUser and therefore cannot be canceled")
        await self._state.http.cancel_user_trade(self.id)
        self.state = ETradeOfferState.Canceled
        self._state.dispatch('trade_cancel', self)

    async def fetch_items(self, user_id64, assets):
        items = await self._state.http.fetch_trade_items(user_id64=user_id64, assets=assets)
        to_ret = []
        for asset in assets:
            for item in items:
                if item.asset_id == asset['assetid'] and item.class_id == asset['classid'] \
                        and item.instance_id == asset['instanceid']:
                    ignore = False
                    if item.name is None:
                        # this is awful I am aware but getting identical items and assets are annoying
                        for item_ in to_ret:
                            if repr(item.asset) == repr(item_.asset):  # idu why this is the only thing that works
                                ignore = True
                    if not ignore:  # this is equally dumb
                        to_ret.append(item)
                    continue
        return to_ret

    def is_one_sided(self):
        return True if self.items_to_receive and not self.items_to_give else False


class Inventory:
    """Represents a User's inventory.

    Attributes
    -------------
    items: List[class:`Item`]
        A list of the inventories owner's items.
    owner: class:`~steam.User`
        The owner of the inventory.
    game: class:`steam.Game`
        The game the inventory the game belongs to.
    """

    __slots__ = ('items', 'owner', 'game', '_data', '_state')

    def __init__(self, state, data, owner):
        self._state = state
        self.owner = owner
        self.items = []
        self._update(data)

    def __repr__(self):
        attrs = (
            'owner', 'game'
        )
        resolved = [f'{attr}={repr(getattr(self, attr))}' for attr in attrs]
        return f"<Inventory {' '.join(resolved)}>"

    def __len__(self):
        return self._data['total_inventory_count']

    def _update(self, data):
        self._data = data
        self.game = Game(app_id=int(data['assets'][0]['appid']), is_steam_game=False)
        for asset in data['assets']:
            for item in data['descriptions']:
                if item['instanceid'] == asset['instanceid'] and item['classid'] == asset['classid']:
                    item.update(asset)
                    self.items.append(Item(data=item))
                    continue
            self.items.append(Item(data=asset, missing=True))
            continue

    def filter_items(self, item_name: str):
        """Filters items by name into a list of one type of item.

        Parameters
        ------------
        item_name: `str`
            The item to filter.

        Returns
        ---------
        Items: :class:`list`
            List of `Item`s
            This also removes the item from the inventory.
        """
        items = [item for item in self.items if item.name == item_name]
        for item in items:
            self.items.remove(item)
        return items

    def get_item(self, item_name: str):
        """Get an item by name from a :class:`Inventory`.

        Parameters
        ----------
        item_name: `str`
            The item to get from the inventory.

        Returns
        -------
        Item: :class:`Item`
            Returns the first found item with a matching name.
            This also removes the item from the inventory.
        """
        item = [item for item in self.items if item.name == item_name][0]
        self.items.remove(item)
        return item


class Asset:
    __slots__ = ('id', 'app_id', 'class_id', 'amount', 'instance_id', 'game')

    def __init__(self, data):
        self.id = data['assetid']
        self.game = Game(app_id=data['appid'])
        self.app_id = data['appid']
        self.amount = int(data['amount'])
        self.instance_id = data['instanceid']
        self.class_id = data['classid']

    def __repr__(self):
        resolved = [f'{attr}={repr(getattr(self, attr))}' for attr in self.__slots__]
        return f"<Asset {' '.join(resolved)}>"

    def __iter__(self):
        for key, value in zip(
                ('assetid', 'amount', 'appid', 'contextid'),
                (self.id, self.amount, self.game.app_id, str(self.game.context_id))
        ):
            yield (key, value)


class Item(Asset):
    """Represents an item in an User's inventory.

    Attributes
    -------------
    name: class:`str`
        The name of the item.
    asset: class:`Asset`
        The item as an asset.
    game: class:`~steam.Game`
        The game the item is from.
    asset_id: class:`str`
        The assetid of the item.
    app_id: class:`str`
        The appid of the item.
    amount: class:`int`
        The amount of the item the inventory contains.
    instance_id: class:`str`
        The instanceid of the item.
    class_id: class:`str`
        The classid of the item.
    colour: Optional[class:`int`]
        The colour of the item.
    market_name: Optional[class:`str`]
        The market_name of the item.
    descriptions: Optional[class:`str`]
        The descriptions of the item.
    type: Optional[class:`str`]
        The type of the item.
    tags: Optional[class:`str`]
        The tags of the item.
    icon_url: Optional[class:`str`]
        The icon_url of the item.
    icon_url_large: Optional[class:`str`]
        The icon_url_large of the item.
    """

    __slots__ = ('name', 'game', 'asset', 'asset_id', 'app_id', 'colour', 'market_name',
                 'descriptions', 'type', 'tags', 'class_id', 'amount', 'instance_id',
                 'icon_url', 'icon_url_large', 'missing', '_data')

    def __init__(self, data, missing: bool = False):
        super().__init__(data)
        self.missing = missing
        self._update(data)

    def __repr__(self):
        attrs = (
            'name', 'asset',
        )
        resolved = [f'{attr}={repr(getattr(self, attr))}' for attr in attrs]
        return f"<Item {' '.join(resolved)}>"

    def _update(self, data):
        self.asset = Asset(data)
        self.game = self.asset.game
        self.asset_id = self.asset.id
        self.app_id = self.asset.app_id
        self.amount = self.asset.amount
        self.instance_id = self.asset.instance_id
        self.class_id = self.asset.class_id

        self.name = data.get('name')
        self.colour = int(data['name_color'], 16) if 'name_color' in data.keys() else None
        self.market_name = data.get('market_name')
        self.descriptions = data.get('descriptions')
        self.type = data.get('type')
        self.tags = data.get('tags')
        self.icon_url = f'https://steamcommunity-a.akamaihd.net/economy/image/{data.get("icon_url")}' \
            if 'icon_url' in data.keys() else None
        self.icon_url_large = f'https://steamcommunity-a.akamaihd.net/economy/image/{data["icon_url_large"]}' \
            if 'icon_url_large' in data.keys() else None
        self._data = data

    def is_tradable(self):
        """Whether or not the item is tradable."""
        return bool(self._data['tradable']) if 'tradable' in self._data.keys() else False

    def is_marketable(self):
        """Whether or not the item is marketable."""
        bool(self._data['marketable']) if 'marketable' in self._data.keys() else False
