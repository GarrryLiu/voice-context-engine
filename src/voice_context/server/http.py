async def limited_body(request,limit):
    output=bytearray()
    async for block in request.stream():
        if len(output)+len(block)>limit:return None
        output.extend(block)
    return bytes(output)

