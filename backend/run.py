import asyncio
from argparse import ArgumentParser

# TODO: подключить выборочный запуск основного API и API для ML

args = ArgumentParser(description="Запуск backend")
args.add_argument("TYPE", 
                  choices=["prod", "dev"], 
                  help="Тип запуска")


async def _production_main():
    pass

async def _development_main():
    pass

async def main():
    if args.TYPE == "prod":
        await _production_main()
    elif args.TYPE == "dev":
        await _development_main()

if __name__ == "__main__":
    asyncio.run(main())