from rapidfuzz import process, fuzz, utils

def match_products(query: str, products: list, limit: int = 5, score_cutoff: float = 50.0) -> list:
    """
    Perform fuzzy matching of a text query against a list of Product models.
    Returns list of tuples: (product_obj, score)
    """
    if not query or not products:
        return []
    
    # Extract product names
    product_names = [p.name for p in products]
    matches = process.extract(
        query, 
        product_names, 
        scorer=fuzz.token_set_ratio, 
        processor=utils.default_process,
        limit=limit,
        score_cutoff=score_cutoff
    )
    
    result = []
    # process.extract returns list of (matched_string, score, index)
    for name, score, idx in matches:
        result.append((products[idx], score))
    return result
