"""tr→en Argos dil paketini indirip kurar (bir kez). Çalıştır:
    cd backend/common && uv run python scripts/install_argos_tr_en.py
"""
import argostranslate.package


def main() -> None:
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    pkg = next(p for p in available if p.from_code == "tr" and p.to_code == "en")
    path = pkg.download()
    argostranslate.package.install_from_path(path)
    print("tr-en paketi kuruldu (translate-tr_en).")


if __name__ == "__main__":
    main()
