
from decimal import Decimal
from pathlib import Path

import transaction
from BTrees.OOBTree import OOBTree
from persistent import Persistent
from persistent.list import PersistentList
from ZODB import DB
from ZODB.FileStorage import FileStorage


RUTA_BD = Path("datos") / "biblioteca_indexada.fs"


class Autor(Persistent):

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.libros = PersistentList()

    def __repr__(self) -> str:
        return f"Autor(nombre={self.nombre!r})"


class Libro(Persistent):

    def __init__(
        self,
        isbn: str,
        titulo: str,
        autor: Autor,
        precio: Decimal
    ) -> None:
        self.isbn = isbn
        self.titulo = titulo
        self.autor = autor
        self.precio = precio

    def __repr__(self) -> str:
        return (
            f"Libro("
            f"isbn={self.isbn!r}, "
            f"titulo={self.titulo!r}, "
            f"autor={self.autor.nombre!r}, "
            f"precio={self.precio!r}"
            f")"
        )


def normalizar(texto: str) -> str:
    """
    Normaliza una cadena utilizada como clave.
    """
    return texto.strip().casefold()


def abrir_base():
    """
    Abre FileStorage, DB, Connection y root.
    """
    RUTA_BD.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    storage = FileStorage(str(RUTA_BD))
    db = DB(storage)
    conexion = db.open()
    root = conexion.root()

    return storage, db, conexion, root


def preparar_estructuras(root) -> None:
    """
    Crea las colecciones persistentes necesarias.
    """
    if "autores" not in root:
        root["autores"] = OOBTree()

    if "libros" not in root:
        root["libros"] = OOBTree()

    if "libros_por_titulo" not in root:
        root["libros_por_titulo"] = OOBTree()

    if "libros_por_autor" not in root:
        root["libros_por_autor"] = OOBTree()

    if "libros_por_precio" not in root:
        root["libros_por_precio"] = OOBTree()


def obtener_o_crear_autor(root, nombre: str) -> Autor:
    """
    Recupera un autor existente o crea uno nuevo.
    """
    clave = normalizar(nombre)
    autor = root["autores"].get(clave)

    if autor is None:
        autor = Autor(nombre)
        root["autores"][clave] = autor

    return autor


def añadir_a_indice_multiple(
    indice,
    clave,
    libro: Libro
) -> None:
    """
    Añade un libro a un índice que admite
    varios libros por cada clave.
    """
    if clave not in indice:
        indice[clave] = PersistentList()

    lista = indice[clave]

    if libro not in lista:
        lista.append(libro)


def eliminar_de_indice_multiple(
    indice,
    clave,
    libro: Libro
) -> None:
    """
    Elimina un libro de un índice múltiple.
    Si la lista queda vacía, elimina la clave.
    """
    if clave not in indice:
        return

    lista = indice[clave]

    if libro in lista:
        lista.remove(libro)

    if not lista:
        del indice[clave]


def indexar_libro(root, libro: Libro) -> None:
    """
    Añade el libro a los índices secundarios.
    """
    clave_titulo = normalizar(libro.titulo)
    clave_autor = normalizar(libro.autor.nombre)

    añadir_a_indice_multiple(
        root["libros_por_titulo"],
        clave_titulo,
        libro
    )

    añadir_a_indice_multiple(
        root["libros_por_autor"],
        clave_autor,
        libro
    )

    añadir_a_indice_multiple(
        root["libros_por_precio"],
        libro.precio,
        libro
    )


def desindexar_libro(
    root,
    libro: Libro,
    titulo_anterior: str | None = None,
    autor_anterior: Autor | None = None,
    precio_anterior: Decimal | None = None
) -> None:
    """
    Retira el libro de los índices.

    Los valores anteriores permiten eliminar
    correctamente las entradas antiguas
    durante una modificación.
    """
    titulo = (
        titulo_anterior
        if titulo_anterior is not None
        else libro.titulo
    )

    autor = (
        autor_anterior
        if autor_anterior is not None
        else libro.autor
    )

    precio = (
        precio_anterior
        if precio_anterior is not None
        else libro.precio
    )

    eliminar_de_indice_multiple(
        root["libros_por_titulo"],
        normalizar(titulo),
        libro
    )

    eliminar_de_indice_multiple(
        root["libros_por_autor"],
        normalizar(autor.nombre),
        libro
    )

    eliminar_de_indice_multiple(
        root["libros_por_precio"],
        precio,
        libro
    )


def añadir_libro(
    root,
    isbn: str,
    titulo: str,
    nombre_autor: str,
    precio: Decimal
) -> Libro:
    """
    Crea, relaciona, guarda e indexa un libro.
    """
    isbn = isbn.strip()
    titulo = titulo.strip()
    nombre_autor = nombre_autor.strip()

    if not isbn:
        raise ValueError("El ISBN es obligatorio.")

    if not titulo:
        raise ValueError("El título es obligatorio.")

    if not nombre_autor:
        raise ValueError("El autor es obligatorio.")

    if precio <= 0:
        raise ValueError("El precio debe ser positivo.")

    if isbn in root["libros"]:
        raise ValueError("Ya existe un libro con ese ISBN.")

    autor = obtener_o_crear_autor(root, nombre_autor)

    libro = Libro(
        isbn=isbn,
        titulo=titulo,
        autor=autor,
        precio=precio
    )

    autor.libros.append(libro)
    root["libros"][isbn] = libro

    indexar_libro(root, libro)

    return libro


def buscar_por_isbn(root, isbn: str) -> Libro | None:
    """
    Búsqueda directa en la colección principal.
    """
    return root["libros"].get(isbn.strip())


def buscar_por_titulo(root, titulo: str) -> list[Libro]:
    """
    Busca libros mediante el índice por título.
    """
    clave = normalizar(titulo)
    coleccion = root["libros_por_titulo"].get(clave)

    if coleccion is None:
        return []

    return list(coleccion)


def buscar_por_autor(root, nombre_autor: str) -> list[Libro]:
    """
    Busca libros mediante el índice por autor.
    """
    clave = normalizar(nombre_autor)
    coleccion = root["libros_por_autor"].get(clave)

    if coleccion is None:
        return []

    return list(coleccion)


def buscar_por_precio(
    root,
    precio_minimo: Decimal,
    precio_maximo: Decimal
) -> list[Libro]:
    """
    Recupera libros dentro de un intervalo.
    """
    if precio_minimo > precio_maximo:
        raise ValueError(
            "El precio mínimo no puede superar al máximo."
        )

    resultado = []

    for precio, libros in root["libros_por_precio"].items(
        min=precio_minimo,
        max=precio_maximo
    ):
        resultado.extend(libros)

    resultado.sort(
        key=lambda libro: (
            libro.precio,
            normalizar(libro.titulo)
        )
    )

    return resultado


def actualizar_libro(
    root,
    isbn: str,
    nuevo_titulo: str,
    nuevo_autor: str,
    nuevo_precio: Decimal
) -> bool:
    """
    Actualiza un libro y sincroniza relaciones
    e índices.
    """
    libro = buscar_por_isbn(root, isbn)

    if libro is None:
        return False

    if not nuevo_titulo.strip():
        raise ValueError("El título es obligatorio.")

    if not nuevo_autor.strip():
        raise ValueError("El autor es obligatorio.")

    if nuevo_precio <= 0:
        raise ValueError("El precio debe ser positivo.")

    titulo_anterior = libro.titulo
    autor_anterior = libro.autor
    precio_anterior = libro.precio

    desindexar_libro(
        root,
        libro,
        titulo_anterior,
        autor_anterior,
        precio_anterior
    )

    autor_anterior.libros.remove(libro)

    autor = obtener_o_crear_autor(
        root,
        nuevo_autor.strip()
    )

    libro.titulo = nuevo_titulo.strip()
    libro.autor = autor
    libro.precio = nuevo_precio

    autor.libros.append(libro)

    indexar_libro(root, libro)

    return True


def eliminar_libro(root, isbn: str) -> bool:
    """
    Elimina un libro de la colección,
    la relación y los índices.
    """
    libro = buscar_por_isbn(root, isbn)

    if libro is None:
        return False

    desindexar_libro(root, libro)

    libro.autor.libros.remove(libro)

    del root["libros"][libro.isbn]

    return True


def mostrar_libros(libros: list[Libro]) -> None:

    if not libros:
        print("No se encontraron libros.")
        return

    for libro in libros:
        print(
            f"{libro.isbn} | "
            f"{libro.titulo} | "
            f"{libro.autor.nombre} | "
            f"{libro.precio:.2f} €"
        )


def main() -> None:
    storage = None
    db = None
    conexion = None

    try:
        storage, db, conexion, root = abrir_base()

        preparar_estructuras(root)

        # Añadir los libros solamente si no existen.
        # Así se evita el error de ISBN duplicado
        # al ejecutar el programa por segunda vez.

        if buscar_por_isbn(root, "9780000002001") is None:
            añadir_libro(
                root,
                isbn="9780000002001",
                titulo="ZODB práctico",
                nombre_autor="Ana Ruiz",
                precio=Decimal("24.90")
            )

        if buscar_por_isbn(root, "9780000002002") is None:
            añadir_libro(
                root,
                isbn="9780000002002",
                titulo="Índices persistentes",
                nombre_autor="Ana Ruiz",
                precio=Decimal("29.50")
            )

        if buscar_por_isbn(root, "9780000002003") is None:
            añadir_libro(
                root,
                isbn="9780000002003",
                titulo="Grafos de objetos",
                nombre_autor="Luis Martín",
                precio=Decimal("35.00")
            )

        transaction.commit()

        print("\n--- BÚSQUEDA POR ISBN ---")
        print(buscar_por_isbn(root, "9780000002001"))

        print("\n--- BÚSQUEDA POR TÍTULO ---")
        mostrar_libros(
            buscar_por_titulo(root, "ZODB PRÁCTICO")
        )

        print("\n--- BÚSQUEDA POR AUTOR ---")
        mostrar_libros(
            buscar_por_autor(root, "ANA RUIZ")
        )

        print("\n--- RANGO DE PRECIOS ---")
        mostrar_libros(
            buscar_por_precio(
                root,
                Decimal("20.00"),
                Decimal("30.00")
            )
        )

    except ValueError as error:
        transaction.abort()
        print("Datos incorrectos:", error)

    except Exception as error:
        transaction.abort()
        print(
            "Se produjo un error. "
            "La transacción se ha cancelado."
        )
        print(error)

    finally:
        if conexion is not None:
            conexion.close()

        if db is not None:
            db.close()

        if storage is not None:
            storage.close()


if __name__ == "__main__":
    main()
