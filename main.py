import typer 

def main(name: str = "Amanda"):
    """Say hello to a specified name."""
    print(f"Hello, {name}!")

if __name__ == "__main__":
    typer.run(main)