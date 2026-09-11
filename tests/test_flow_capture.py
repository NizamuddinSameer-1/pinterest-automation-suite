from app.services.flow_media import (
    harvest_media,
    looks_like_generation_url,
    media_identifier,
    MediaHarvest,
)

def test_looks_like_generation_url_flow_content():
    url = "https://flow-content.google/image/e0368942-f0dd-40b1-a309-f0206f8ea1ce?Expires=1789088607&KeyName=labs-flow-prod-cdn-key&Signature=dXI6AJmZjI-j15IWQOWMH2al--A"
    assert looks_like_generation_url(url) is True

    # RPC endpoint
    rpc_url = "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=ogiZ0b"
    assert looks_like_generation_url(rpc_url) is True

    # Listing or history endpoint should be excluded
    history_url = "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=listMedia"
    assert looks_like_generation_url(history_url) is False


def test_media_identifier():
    cdn_url = "https://flow-content.google/image/e0368942-f0dd-40b1-a309-f0206f8ea1ce?Expires=1789088607&KeyName=labs-flow-prod-cdn-key&Signature=dXI6AJmZjI-j15IWQOWMH2al--A"
    assert media_identifier(cdn_url) == "e0368942-f0dd-40b1-a309-f0206f8ea1ce"

    asb_url = "https://flow.google.com/asb/AB-nOUZDmuIvPrQUIkZ-er5PEViwmZyXEVmDBkGfXHnl9pjWhOS9kloQoQeQP=s512-rw"
    assert media_identifier(asb_url) == "AB-nOUZDmuIvPrQUIkZ-er5PEViwmZyXEVmDBkGfXHnl9pjWhOS9kloQoQeQP"


def test_harvest_media_flow_content():
    raw_response = (
        r')]}' + "\n"
        r'[["wrb.fr","ogiZ0b","[\"https:\/\/flow-content.google\/image\/70a93c72-86ff-4e13-b788-e2088a69ae0f?Expires=1789088607&KeyName=labs-flow-prod-cdn-key&Signature=Q9EQobw1LRYQ8jJfk4-pY3qNXng\"]"]'
    )
    harvest = harvest_media(raw_response)
    assert harvest.total == 1
    assert "https://flow-content.google/image/70a93c72-86ff-4e13-b788-e2088a69ae0f" in harvest.urls[0]
