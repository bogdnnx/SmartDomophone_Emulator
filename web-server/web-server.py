import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class Book(BaseModel):
    id: int
    title: str = Field(max_length=30)
    author: str = Field(max_length=50)


books = []


@app.get('/books')
def get_all_books():
    return books

@app.get('/books/{id}')
def get_book_by_id(id: int):
    return books[id-1] if id<= len(books) else HTTPException(404, "book not found")



@app.post('/books')
def create_book(new_book:Book):
    books.append(new_book)
    return {"ok": True}


@app.get('/', tags=['тест ручки'], summary='abc')
def root():
    return 'Hi'




if __name__=="__main__":
    uvicorn.run("main:app", reload=True)