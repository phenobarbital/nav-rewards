from datamodel import BaseModel
from navigator.views import ModelView
from navigator.views.abstract import AbstractModel
from aiohttp import web
from asyncdb.exceptions import NoDataFound
from .models import ADUser, ADPeople


class ADUserHandler(ModelView):
    model: BaseModel = ADUser
    pk: str = 'people_id'


class ADPeopleHandler(ModelView):
    model: BaseModel = ADPeople
    pk: str = 'people_id'


class ADPeopleSearchHandler(AbstractModel):
    """Search handler for AD People."""
    path = 'ad_people/search'
    model = ADPeople
    
    async def get(self):
        """Search for people by query string across multiple fields."""
        qp = self.query_parameters(self.request)
        query = qp.get('query', '').strip()
        
        if not query:
            return self.json_response(
                {"error": "Query parameter is required"},
                status=400
            )
        
        search_pattern = f"%{query}%"
        
        try:
            async with await self.handler(request=self.request) as conn:
                sql = """
                    SELECT * FROM troc.vw_people 
                    WHERE display_name ILIKE $1 
                       OR given_name ILIKE $1 
                       OR last_name ILIKE $1 
                       OR email ILIKE $1 
                       OR username ILIKE $1
                    ORDER BY display_name
                    LIMIT 100
                """
                
                result = await conn.fetchall(sql, search_pattern)
            
                data = []
                for row in result:
                    data.append(dict(row))
                
                return self.json_response(data)
                
        except Exception as err:
            return self.error(
                response={"error": f"Search failed: {str(err)}"},
                status=500
            )
