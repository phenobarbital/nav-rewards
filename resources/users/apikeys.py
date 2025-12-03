""""
App Views.
"""
from typing import Union
from asyncdb.exceptions import NoDataFound
from navigator.views import ModelView
from navigator_auth.models import UserDevices
from .models import APIKeys
from uuid import uuid4

class APIKeysView(ModelView):
    model = APIKeys
    pk: list = ['user_id', 'device_id']

    async def _post_data(self) -> Union[dict, list]:
        data = await self.json_data()
        if 'device_id' in data:
            # estoy editando
            return self.error(
                response={"error": "You can't edit the an API Key"},
                status=400
            )
        else:
            # estoy creando un nuevo api key
            params = {
                "created_by": self._userid,
                "device_id": uuid4(),
                **data
            }
            # Create API Key
            result = UserDevices(**params)
            response = result.to_dict()
            del response['issuer']
        return response

    async def delete(self):
        ''' Update Field revoked to TRUE
        '''
        args, _, _, _ = self.get_parameters()
        user_id = None
        name = None
        device_id = None
        if 'id' in args:
            device_id = args.get('id')
        else:
            device_id = None
        payload = await self.json_data()
        if payload:
            if 'device_id' in payload:
                device_id = payload.get('device_id')
            if payload is not None:
                user_id = payload.user_id
                name = payload.name
        async with await self.handler(request=self.request) as conn:
            self.model.Meta.connection = conn
            try:
                if device_id:
                    api_key = await self.model.get(
                        device_id=device_id
                    )
                else:
                    api_key = await self.model.get(user_id=user_id, name=name)
                api_key.revoked = True
                await api_key.update()
                return self.json_response(status=200, response=api_key)
            except NoDataFound:
                return self.error(
                    response={
                        "error": f"API Key not exists with user_id '{user_id }' and name '{name}'"
                    },
                    status=404
                )
