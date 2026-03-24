import os
import logging
import requests
import tempfile
import uuid
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
import xml.etree.ElementTree as ET
import gzip
import base64
from datetime import datetime
from xml.sax.saxutils import escape
import re

logger = logging.getLogger(__name__)

# URL do serviço de Distribuição de DFe (Ambiente Nacional)
URL_DISTRIBUICAO = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
URL_RECEPCAO_EVENTO = "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx" # Exemplo, varia por UF para NFe, mas Manifestação é AN
URL_MANIFESTACAO = "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx" # Ambiente Nacional

class SefazService:
    def __init__(self, pfx_path, pfx_password):
        self.pfx_path = pfx_path
        self.pfx_password = pfx_password
        self._cert_pem = None
        self._key_pem = None
        self._temp_dir = None
        self._certificate_metadata = {}
        self._xml_signature_profile = {
            "signature_algorithm": "rsa-sha1",
            "digest_algorithm": "sha1",
            "c14n_algorithm": "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
        }

    def _inspect_xml_prefix_usage(self, xml_text):
        text = str(xml_text or "")
        prefixes = re.findall(r"</?([A-Za-z_][\w\.-]*):[A-Za-z_][\w\.-]*", text)
        unique = sorted(set(prefixes))
        root_match = re.search(r"<([A-Za-z_][\w\.-]*(?::[A-Za-z_][\w\.-]*)?)", text)
        return {
            "has_prefixes": len(unique) > 0,
            "prefixes": unique,
            "has_nfe_prefixes": any(p.lower().startswith("nfe") or p.lower().startswith("ns") for p in unique),
            "has_ds_prefix": "ds" in unique,
            "root_tag": root_match.group(1) if root_match else "",
            "signature_present": ("<Signature" in text) or ("<ds:Signature" in text),
        }

    def _ensure_event_xsd_tree(self):
        base_url = "https://raw.githubusercontent.com/akretion/nfelib/master_gen_v4_00/schemas/nfe/v4_00/"
        cache_dir = os.path.join(os.getcwd(), "data", "fiscal", "xsd_cache", "nfe_v4_00")
        os.makedirs(cache_dir, exist_ok=True)
        visited = set()

        def download_file(filename):
            name = str(filename or "").strip()
            if not name or name in visited:
                return
            visited.add(name)
            local_path = os.path.join(cache_dir, name)
            if not os.path.exists(local_path):
                resp = requests.get(base_url + name, timeout=20)
                resp.raise_for_status()
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(resp.text)
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            for ref in re.findall(r'schemaLocation="([^"]+\.xsd)"', content):
                if "://" in ref:
                    continue
                download_file(ref)

        download_file("envEvento_v1.00.xsd")
        return os.path.join(cache_dir, "envEvento_v1.00.xsd")

    def _validate_event_xml_schema(self, xml_text):
        try:
            from lxml import etree
            xsd_path = self._ensure_event_xsd_tree()
            schema_doc = etree.parse(xsd_path)
            schema = etree.XMLSchema(schema_doc)
            doc = etree.fromstring(str(xml_text or "").encode("utf-8"))
            ok = bool(schema.validate(doc))
            if ok:
                return {"ok": True, "line": 0, "message": ""}
            err = schema.error_log.last_error
            return {
                "ok": False,
                "line": int(getattr(err, "line", 0) or 0),
                "message": str(getattr(err, "message", "") or "Falha de schema"),
            }
        except Exception as e:
            return {"ok": False, "line": 0, "message": str(e)}

    def __enter__(self):
        self._load_cert()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()

    def _load_cert(self):
        """Carrega o certificado PFX e converte para PEM temporário para uso no requests."""
        try:
            with open(self.pfx_path, "rb") as f:
                pfx_data = f.read()

            password = self.pfx_password.encode('utf-8') if self.pfx_password else None
            
            # Carregar PFX
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                pfx_data, 
                password
            )
            if private_key is None or certificate is None:
                raise Exception("Certificado A1 inválido: chave privada ou certificado ausente no PFX.")

            # Criar diretório temporário
            self._temp_dir = tempfile.TemporaryDirectory()
            
            cert_path = os.path.join(self._temp_dir.name, "cert.pem")
            key_path = os.path.join(self._temp_dir.name, "key.pem")

            # Salvar Certificado
            with open(cert_path, "wb") as f:
                f.write(certificate.public_bytes(serialization.Encoding.PEM))
                if additional_certificates:
                    for cert in additional_certificates:
                        f.write(cert.public_bytes(serialization.Encoding.PEM))

            # Salvar Chave Privada
            with open(key_path, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))

            self._cert_pem = cert_path
            self._key_pem = key_path
            self._certificate_metadata = {
                "serial_number": str(getattr(certificate, "serial_number", "")),
                "fingerprint_sha256": certificate.fingerprint(hashes.SHA256()).hex().upper(),
                "subject": str(certificate.subject.rfc4514_string() or ""),
                "issuer": str(certificate.issuer.rfc4514_string() or ""),
                "not_valid_before": certificate.not_valid_before_utc.isoformat() if hasattr(certificate, "not_valid_before_utc") else "",
                "not_valid_after": certificate.not_valid_after_utc.isoformat() if hasattr(certificate, "not_valid_after_utc") else "",
            }
            logger.info(
                "sefaz_certificate_loaded path=%s subject=%s serial=%s valid_to=%s",
                str(self.pfx_path),
                str(self._certificate_metadata.get("subject") or ""),
                str(self._certificate_metadata.get("serial_number") or ""),
                str(self._certificate_metadata.get("not_valid_after") or ""),
            )
            
        except Exception as e:
            logger.error(f"Erro ao carregar certificado PFX: {e}")
            raise

    def load_certificate(self):
        if not self._cert_pem or not self._key_pem:
            self._load_cert()
        return {
            "ok": bool(self._cert_pem and self._key_pem),
            "cert_pem": self._cert_pem,
            "key_pem": self._key_pem,
            "metadata": dict(self._certificate_metadata or {}),
        }

    def _cleanup(self):
        if self._temp_dir:
            self._temp_dir.cleanup()

    def _build_soap_envelope(self, body_content, method_name=None, namespace=None):
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            '<soap12:Body>'
            '<nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">'
            '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">'
            f'{body_content}'
            '</nfeDadosMsg>'
            '</nfeDistDFeInteresse>'
            '</soap12:Body>'
            '</soap12:Envelope>'
        )

    def _build_event_soap_envelope(
        self,
        body_content,
        cuf_header="91",
        versao_dados="1.00",
        soap_operation="nfeRecepcaoEvento",
        include_nfe_header=True,
        wrap_operation=True,
        payload_mode="cdata",
    ):
        cuf_value = str(cuf_header or "91")
        versao_value = str(versao_dados or "1.00")
        operation_name = str(soap_operation or "nfeRecepcaoEvento")
        payload_raw = str(body_content or "")
        payload_mode_value = str(payload_mode or "cdata").strip().lower()
        if payload_mode_value == "xml_node":
            nfe_payload = payload_raw
            payload_node_type = "xml_node"
        elif payload_mode_value == "escaped":
            nfe_payload = escape(payload_raw)
            payload_node_type = "text_escaped"
        else:
            cdata_payload = payload_raw.replace("]]>", "]]]]><![CDATA[>")
            nfe_payload = f'<![CDATA[{cdata_payload}]]>'
            payload_mode_value = "cdata"
            payload_node_type = "cdata_text"
        header_block = (
            '<soap:Header>'
            '<nfeCabecMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">'
            f'<cUF>{cuf_value}</cUF>'
            f'<versaoDados>{versao_value}</versaoDados>'
            '</nfeCabecMsg>'
            '</soap:Header>'
        ) if bool(include_nfe_header) else '<soap:Header />'
        if bool(wrap_operation):
            body_block = (
                f'<{operation_name} xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">'
                '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">'
                f'{nfe_payload}'
                '</nfeDadosMsg>'
                f'</{operation_name}>'
            )
        else:
            body_block = (
                '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">'
                f'{nfe_payload}'
                '</nfeDadosMsg>'
            )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'{header_block}'
            '<soap:Body>'
            f'{body_block}'
            '</soap:Body>'
            '</soap:Envelope>'
        ), payload_mode_value, payload_node_type

    def _extract_event_request_context(self, xml_evento):
        context = {"cuf_header": "91", "cuf_source": "fallback_91", "versao_dados": "1.00", "tp_amb": "1", "event_id": "", "event_version": "1.00", "det_event_version": ""}
        chave_nfe = ""
        c_orgao = ""
        try:
            root = ET.fromstring(str(xml_evento or "").encode("utf-8"))
            tag_versao = str(root.attrib.get("versao") or "").strip()
            if tag_versao:
                context["versao_dados"] = tag_versao
                context["event_version"] = tag_versao
            for node in root.iter():
                tag = str(getattr(node, "tag", ""))
                text = str(getattr(node, "text", "") or "").strip()
                if tag.endswith("infEvento") and not context["event_id"]:
                    context["event_id"] = str(getattr(node, "attrib", {}).get("Id") or "")
                if tag.endswith("detEvento") and not context["det_event_version"]:
                    context["det_event_version"] = str(getattr(node, "attrib", {}).get("versaoEvento") or getattr(node, "attrib", {}).get("versao") or "")
                if not text:
                    continue
                if tag.endswith("chNFe") and len(text) >= 2 and not chave_nfe:
                    chave_nfe = text
                elif tag.endswith("cOrgao") and len(text) == 2 and not c_orgao:
                    c_orgao = text
                elif tag.endswith("tpAmb") and text in {"1", "2"}:
                    context["tp_amb"] = text
            if len(chave_nfe) >= 2 and chave_nfe[:2].isdigit():
                context["cuf_header"] = chave_nfe[:2]
                context["cuf_source"] = "chNFe_prefix"
            elif len(c_orgao) == 2 and c_orgao.isdigit():
                context["cuf_header"] = c_orgao
                context["cuf_source"] = "cOrgao"
        except Exception:
            pass
        return context

    def _digits_only(self, value):
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    def confirmar_operacao(self, chave_acesso, cnpj, ambiente=1):
        """
        Envia evento de Confirmação da Operação (210200) para a SEFAZ.
        """
        xml_evento = self._gerar_xml_evento(chave_acesso, cnpj, "210200", "Confirmacao da Operacao", ambiente)
        return self._enviar_evento(xml_evento, ambiente)

    def manifestar_ciencia_operacao(self, chave_acesso, cnpj, ambiente=1, sequencia_evento=1, correlation_id=None, binding_profile=None):
        cnpj_value = self._digits_only(cnpj)
        key_value = self._digits_only(chave_acesso)
        if len(cnpj_value) != 14:
            return {"success": False, "message": "CNPJ do destinatário inválido."}
        if len(key_value) != 44:
            return {"success": False, "message": "Chave da NF-e inválida."}
        try:
            logger.info(
                "sefaz_manifest_prepare key=%s seq=%s ambiente=%s",
                str(key_value),
                str(sequencia_evento),
                str(ambiente),
            )
            xml_evento = self._gerar_xml_evento(
                key_value,
                cnpj_value,
                "210210",
                "Ciencia da Operacao",
                ambiente,
                sequencia_evento=sequencia_evento,
                correlation_id=correlation_id,
            )
            logger.info("sefaz_manifest_xml_signed key=%s xml_length=%s", str(key_value), len(str(xml_evento or "")))
            return self._enviar_evento(xml_evento, ambiente, correlation_id=correlation_id, binding_profile=binding_profile)
        except Exception as e:
            logger.error(f"Erro ao manifestar ciência da operação: {e}")
            return {"success": False, "message": str(e)}

    def _gerar_xml_evento(self, chave, cnpj, tp_evento, desc_evento, ambiente, sequencia_evento=1, correlation_id=None):
        now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S-03:00')
        seq = int(sequencia_evento or 1)
        event_version = "1.00"
        det_event_version = "1.00"
        event_id = f"ID{tp_evento}{chave}{str(seq).zfill(2)}"
        logger.info(
            "sefaz_manifest_event_build correlation_id=%s event_version=%s detEvento_version=%s tpEvento=%s nSeqEvento=%s xml_id=%s schema_validation_mode=sefaz_evento_v1",
            str(correlation_id or ""),
            event_version,
            det_event_version,
            str(tp_evento),
            str(seq),
            event_id,
        )
        xml = (
            f'<envEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="{event_version}">'
            f'<idLote>{str(uuid.uuid4().int)[:15]}</idLote>'
            f'<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="{event_version}">'
            f'<infEvento Id="{event_id}">'
            f'<cOrgao>91</cOrgao>'
            f'<tpAmb>{int(ambiente)}</tpAmb>'
            f'<CNPJ>{cnpj}</CNPJ>'
            f'<chNFe>{chave}</chNFe>'
            f'<dhEvento>{now}</dhEvento>'
            f'<tpEvento>{tp_evento}</tpEvento>'
            f'<nSeqEvento>{seq}</nSeqEvento>'
            f'<verEvento>1.00</verEvento>'
            f'<detEvento versao="{det_event_version}">'
            f'<descEvento>{desc_evento}</descEvento>'
            f'</detEvento>'
            f'</infEvento>'
            f'</evento>'
            f'</envEvento>'
        )
        return self._sign_event_xml(xml, correlation_id=correlation_id)

    def _sign_event_xml(self, event_xml, correlation_id=None):
        try:
            from lxml import etree
            from signxml import XMLSigner, methods
        except Exception:
            raise Exception("Assinatura fiscal indisponível: bibliotecas XML não instaladas no servidor.")
        if not self._cert_pem or not self._key_pem:
            self._load_cert()
        parser = etree.XMLParser(remove_blank_text=True)
        root = etree.fromstring(event_xml.encode("utf-8"), parser=parser)
        evento_node = root.find(".//{http://www.portalfiscal.inf.br/nfe}evento")
        inf_evento = root.find(".//{http://www.portalfiscal.inf.br/nfe}infEvento")
        if inf_evento is None or evento_node is None:
            raise Exception("Estrutura do evento inválida para assinatura.")
        ref_uri = "#" + str(inf_evento.get("Id") or "")
        with open(self._key_pem, "rb") as f:
            key_data = f.read()
        with open(self._cert_pem, "rb") as f:
            cert_data = f.read()
        class LegacyXMLSigner(XMLSigner):
            def check_deprecated_methods(self):
                return None

        signer = LegacyXMLSigner(
            method=methods.enveloped,
            signature_algorithm=str(self._xml_signature_profile.get("signature_algorithm") or "rsa-sha256"),
            digest_algorithm=str(self._xml_signature_profile.get("digest_algorithm") or "sha256"),
            c14n_algorithm=str(self._xml_signature_profile.get("c14n_algorithm") or "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"),
        )
        signer.namespaces = {None: "http://www.w3.org/2000/09/xmldsig#"}
        logger.info(
            "sefaz_manifest_xml_sign_start correlation_id=%s signature_algorithm=%s digest_algorithm=%s c14n=%s signed_node=infEvento ref_uri=%s",
            str(correlation_id or ""),
            str(self._xml_signature_profile.get("signature_algorithm") or ""),
            str(self._xml_signature_profile.get("digest_algorithm") or ""),
            str(self._xml_signature_profile.get("c14n_algorithm") or ""),
            str(ref_uri),
        )
        signed_inf = signer.sign(
            evento_node,
            key=key_data,
            cert=cert_data,
            reference_uri=ref_uri,
            id_attribute="Id",
        )
        evento_node.getparent().replace(evento_node, signed_inf)
        logger.info(
            "sefaz_manifest_xml_sign_ok correlation_id=%s cert_serial=%s cert_fp=%s signature_algorithm=%s digest_algorithm=%s",
            str(correlation_id or ""),
            str(self._certificate_metadata.get("serial_number") or ""),
            str(self._certificate_metadata.get("fingerprint_sha256") or "")[:16],
            str(self._xml_signature_profile.get("signature_algorithm") or ""),
            str(self._xml_signature_profile.get("digest_algorithm") or ""),
        )
        signed_xml = etree.tostring(root, encoding="utf-8", xml_declaration=False).decode("utf-8")
        prefix_info = self._inspect_xml_prefix_usage(signed_xml)
        signature_pos_ok = "<evento" in signed_xml and "</infEvento><Signature" in signed_xml.replace("\n", "").replace("\r", "").replace(" ", "")
        logger.info(
            "sefaz_manifest_xml_namespace_diagnostics correlation_id=%s namespace_mode=default has_prefixes=%s has_nfe_prefixes=%s has_ds_prefix=%s root_tag=%s signature_present=%s signature_position_ok=%s signature_reference_uri=%s prefixes=%s",
            str(correlation_id or ""),
            str(prefix_info.get("has_prefixes")),
            str(prefix_info.get("has_nfe_prefixes")),
            str(prefix_info.get("has_ds_prefix")),
            str(prefix_info.get("root_tag")),
            str(prefix_info.get("signature_present")),
            str(signature_pos_ok),
            str(ref_uri),
            ",".join(prefix_info.get("prefixes") or []),
        )
        return signed_xml

    def _enviar_evento(self, xml_evento, ambiente=1, correlation_id=None, binding_profile=None):
        url = URL_MANIFESTACAO if int(ambiente) == 1 else URL_MANIFESTACAO.replace("www.", "hom.")
        req_ctx = self._extract_event_request_context(xml_evento)
        profile = binding_profile if isinstance(binding_profile, dict) else {}
        soap_operation = str(profile.get("soap_operation") or "nfeRecepcaoEvento")
        soap_action = str(profile.get("soap_action") or f"http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4/{soap_operation}")
        include_nfe_header = bool(profile.get("include_nfe_header", True))
        wrap_operation = bool(profile.get("wrap_operation", True))
        payload_mode = str(profile.get("payload_mode") or ("xml_node" if soap_operation == "nfeRecepcaoEventoNF" else "cdata"))
        envelope, payload_mode_resolved, payload_node_type = self._build_event_soap_envelope(
            xml_evento,
            cuf_header=str(req_ctx.get("cuf_header") or "91"),
            versao_dados=str(req_ctx.get("versao_dados") or "1.00"),
            soap_operation=soap_operation,
            include_nfe_header=include_nfe_header,
            wrap_operation=wrap_operation,
            payload_mode=payload_mode,
        )
        content_type = "text/xml; charset=utf-8"
        headers = {
            "Content-Type": content_type,
            "SOAPAction": f"\"{soap_action}\"",
        }
        payload_prefix_info = self._inspect_xml_prefix_usage(xml_evento)
        xsd_validation = self._validate_event_xml_schema(xml_evento)
        logger.info(
            "sefaz_manifest_xsd_validation correlation_id=%s xsd_validation=%s xsd_error_line=%s xsd_error_message=%s signature_present=%s signature_reference_uri=%s event_version=%s detEvento_version=%s",
            str(correlation_id or ""),
            str(bool(xsd_validation.get("ok"))),
            str(int(xsd_validation.get("line") or 0)),
            str(xsd_validation.get("message") or ""),
            str(payload_prefix_info.get("signature_present")),
            f"#{str(req_ctx.get('event_id') or '')}",
            str(req_ctx.get("event_version") or "1.00"),
            str(req_ctx.get("det_event_version") or ""),
        )
        xsd_message = str(xsd_validation.get("message") or "")
        xsd_infra_issue = ("does not resolve to a(n) type definition" in xsd_message) or ("schema parse" in xsd_message.lower())
        if not bool(xsd_validation.get("ok")) and not xsd_infra_issue:
            return {
                "success": False,
                "message": "XML do evento não validou no schema local antes do envio.",
                "http_status": 0,
                "faultcode": "local:xsd",
                "faultstring": str(xsd_validation.get("message") or ""),
                "cStat": "",
                "xMotivo": str(xsd_validation.get("message") or ""),
                "protocol": "",
                "remote_body_excerpt": "",
                "response_content_type": "",
                "request_diagnostics": {
                    "url": str(url),
                    "soap_action": str(soap_action),
                    "content_type": str(content_type),
                    "layout_version": "1.00",
                    "soap_version": "1.1",
                    "soap_operation": str(soap_operation),
                    "wrap_operation": bool(wrap_operation),
                    "payload_mode": str(payload_mode_resolved),
                    "payload_node_type": str(payload_node_type),
                    "namespace_mode": "default",
                    "payload_has_prefixes": bool(payload_prefix_info.get("has_prefixes")),
                    "payload_has_nfe_prefixes": bool(payload_prefix_info.get("has_nfe_prefixes")),
                    "payload_has_ds_prefix": bool(payload_prefix_info.get("has_ds_prefix")),
                    "payload_prefixes": payload_prefix_info.get("prefixes") if isinstance(payload_prefix_info.get("prefixes"), list) else [],
                    "xsd_validation": False,
                    "xsd_infra_issue": bool(xsd_infra_issue),
                    "xsd_error_line": int(xsd_validation.get("line") or 0),
                    "xsd_error_message": str(xsd_validation.get("message") or ""),
                    "tp_amb": int(req_ctx.get("tp_amb") or ambiente),
                    "soap_header_present": bool(include_nfe_header),
                    "cUF_header": str(req_ctx.get("cuf_header") or "91"),
                    "cUF_source": str(req_ctx.get("cuf_source") or ""),
                    "versaoDados_header": str(req_ctx.get("versao_dados") or "1.00"),
                    "envelope_namespace": "http://schemas.xmlsoap.org/soap/envelope/",
                    "header_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                    "body_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                },
            }
        try:
            logger.info(
                "sefaz_manifest_http_request correlation_id=%s url=%s payload_length=%s soap_version=%s soap_action=%s content_type=%s soap_operation=%s wrap_operation=%s payload_mode=%s payload_node_type=%s namespace_mode=default payload_has_prefixes=%s payload_has_nfe_prefixes=%s payload_has_ds_prefix=%s soap_header_present=%s cUF=%s cUF_source=%s versaoDados=%s envelope_ns=%s header_ns=%s body_ns=%s cert_serial=%s cert_fp=%s",
                str(correlation_id or ""),
                str(url),
                len(envelope),
                "1.1",
                str(soap_action),
                str(content_type),
                str(soap_operation),
                str(bool(wrap_operation)).lower(),
                str(payload_mode_resolved),
                str(payload_node_type),
                str(payload_prefix_info.get("has_prefixes")),
                str(payload_prefix_info.get("has_nfe_prefixes")),
                str(payload_prefix_info.get("has_ds_prefix")),
                str(bool(include_nfe_header)).lower(),
                str(req_ctx.get("cuf_header") or "91"),
                str(req_ctx.get("cuf_source") or ""),
                str(req_ctx.get("versao_dados") or "1.00"),
                "http://schemas.xmlsoap.org/soap/envelope/",
                "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                str(self._certificate_metadata.get("serial_number") or ""),
                str(self._certificate_metadata.get("fingerprint_sha256") or "")[:16],
            )
            response = requests.post(
                url,
                data=envelope.encode("utf-8"),
                headers=headers,
                cert=(self._cert_pem, self._key_pem),
                verify=False,
                timeout=30,
            )
            response_text = response.text or ""
            response_content_type = str(response.headers.get("Content-Type") or "")
            logger.info(
                "sefaz_manifest_http_response correlation_id=%s status=%s content_type=%s",
                str(correlation_id or ""),
                str(response.status_code),
                response_content_type,
            )
            if int(response.status_code) >= 400:
                fault = self._parse_soap_fault(response_text)
                logger.error(
                    "sefaz_manifest_http_fault correlation_id=%s status=%s faultcode=%s faultstring=%s cStat=%s xMotivo=%s body_excerpt=%s",
                    str(correlation_id or ""),
                    str(response.status_code),
                    str(fault.get("faultcode") or ""),
                    str(fault.get("faultstring") or ""),
                    str(fault.get("cStat") or ""),
                    str(fault.get("xMotivo") or ""),
                    str((fault.get("remote_body_excerpt") or "")[:300]),
                )
                message = str(fault.get("faultstring") or fault.get("xMotivo") or f"HTTP {response.status_code} retornado pela SEFAZ.")
                return {
                    "success": False,
                    "message": message,
                    "http_status": int(response.status_code),
                    "faultcode": str(fault.get("faultcode") or ""),
                    "faultstring": str(fault.get("faultstring") or ""),
                    "cStat": str(fault.get("cStat") or ""),
                    "xMotivo": str(fault.get("xMotivo") or ""),
                    "protocol": str(fault.get("nProt") or ""),
                    "remote_body_excerpt": str(fault.get("remote_body_excerpt") or ""),
                    "response_content_type": response_content_type,
                    "request_diagnostics": {
                        "url": str(url),
                        "soap_action": str(soap_action),
                        "content_type": str(content_type),
                        "layout_version": "1.00",
                        "soap_version": "1.1",
                        "soap_operation": str(soap_operation),
                        "wrap_operation": bool(wrap_operation),
                        "payload_mode": str(payload_mode_resolved),
                        "payload_node_type": str(payload_node_type),
                        "namespace_mode": "default",
                        "payload_has_prefixes": bool(payload_prefix_info.get("has_prefixes")),
                        "payload_has_nfe_prefixes": bool(payload_prefix_info.get("has_nfe_prefixes")),
                        "payload_has_ds_prefix": bool(payload_prefix_info.get("has_ds_prefix")),
                        "payload_prefixes": payload_prefix_info.get("prefixes") if isinstance(payload_prefix_info.get("prefixes"), list) else [],
                        "tp_amb": int(req_ctx.get("tp_amb") or ambiente),
                        "soap_header_present": bool(include_nfe_header),
                        "cUF_header": str(req_ctx.get("cuf_header") or "91"),
                        "cUF_source": str(req_ctx.get("cuf_source") or ""),
                        "versaoDados_header": str(req_ctx.get("versao_dados") or "1.00"),
                        "envelope_namespace": "http://schemas.xmlsoap.org/soap/envelope/",
                        "header_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                        "body_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                    },
                }
            parsed = self._parse_event_response(response.content)
            parsed["http_status"] = int(response.status_code)
            parsed["response_content_type"] = response_content_type
            parsed["request_diagnostics"] = {
                "url": str(url),
                "soap_action": str(soap_action),
                "content_type": str(content_type),
                "layout_version": "1.00",
                "soap_version": "1.1",
                "soap_operation": str(soap_operation),
                "wrap_operation": bool(wrap_operation),
                "payload_mode": str(payload_mode_resolved),
                "payload_node_type": str(payload_node_type),
                "namespace_mode": "default",
                "payload_has_prefixes": bool(payload_prefix_info.get("has_prefixes")),
                "payload_has_nfe_prefixes": bool(payload_prefix_info.get("has_nfe_prefixes")),
                "payload_has_ds_prefix": bool(payload_prefix_info.get("has_ds_prefix")),
                "payload_prefixes": payload_prefix_info.get("prefixes") if isinstance(payload_prefix_info.get("prefixes"), list) else [],
                "tp_amb": int(req_ctx.get("tp_amb") or ambiente),
                "soap_header_present": bool(include_nfe_header),
                "cUF_header": str(req_ctx.get("cuf_header") or "91"),
                "cUF_source": str(req_ctx.get("cuf_source") or ""),
                "versaoDados_header": str(req_ctx.get("versao_dados") or "1.00"),
                "envelope_namespace": "http://schemas.xmlsoap.org/soap/envelope/",
                "header_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
                "body_namespace": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
            }
            return parsed
        except Exception as e:
            logger.error(f"Erro no envio de evento de manifestação: {e}")
            return {"success": False, "message": str(e), "http_status": getattr(getattr(e, "response", None), "status_code", None)}

    def _parse_soap_fault(self, xml_text):
        body_text = str(xml_text or "")
        excerpt = body_text[:2000]
        details = {
            "faultcode": "",
            "faultstring": "",
            "cStat": "",
            "xMotivo": "",
            "nProt": "",
            "remote_body_excerpt": excerpt,
        }
        try:
            root = ET.fromstring(body_text.encode("utf-8") if isinstance(body_text, str) else body_text)
            for fault in root.iter():
                if not str(getattr(fault, "tag", "")).endswith("Fault"):
                    continue
                for sub in fault.iter():
                    tag = str(getattr(sub, "tag", ""))
                    text = str(getattr(sub, "text", "") or "").strip()
                    if not text:
                        continue
                    if (tag.endswith("faultcode") or tag.endswith("Value")) and not details["faultcode"]:
                        details["faultcode"] = text
                    elif (tag.endswith("faultstring") or tag.endswith("Text")) and not details["faultstring"]:
                        details["faultstring"] = text
            for node in root.iter():
                tag = str(getattr(node, "tag", ""))
                text = str(getattr(node, "text", "") or "")
                if tag.endswith("faultcode") and text and not details["faultcode"]:
                    details["faultcode"] = text
                elif tag.endswith("faultstring") and text and not details["faultstring"]:
                    details["faultstring"] = text
                elif tag.endswith("cStat") and text and not details["cStat"]:
                    details["cStat"] = text
                elif tag.endswith("xMotivo") and text and not details["xMotivo"]:
                    details["xMotivo"] = text
                elif tag.endswith("nProt") and text and not details["nProt"]:
                    details["nProt"] = text
        except Exception:
            pass
        return details

    def _parse_event_response(self, xml_content):
        try:
            root = ET.fromstring(xml_content)
            def find_first(tag_name, base=None):
                scope = base if base is not None else root
                for node in scope.iter():
                    if str(getattr(node, "tag", "")).endswith(tag_name):
                        return node
                return None

            def find_first_text(tag_name, base=None):
                node = find_first(tag_name, base=base)
                return str(getattr(node, "text", "") or "").strip() if node is not None else ""

            ret_evento = find_first("retEvento")
            inf_evento = find_first("infEvento", base=ret_evento) if ret_evento is not None else None
            lote_cstat = find_first_text("cStat", base=root)
            lote_xmotivo = find_first_text("xMotivo", base=root)
            event_cstat = find_first_text("cStat", base=inf_evento) if inf_evento is not None else ""
            event_xmotivo = find_first_text("xMotivo", base=inf_evento) if inf_evento is not None else ""
            event_protocol = find_first_text("nProt", base=inf_evento) if inf_evento is not None else ""
            event_registered_at = find_first_text("dhRegEvento", base=inf_evento) if inf_evento is not None else ""
            event_type = find_first_text("tpEvento", base=inf_evento) if inf_evento is not None else ""
            event_access_key = find_first_text("chNFe", base=inf_evento) if inf_evento is not None else ""
            event_seq = find_first_text("nSeqEvento", base=inf_evento) if inf_evento is not None else ""
            success_event_codes = {"135", "136", "155", "573", "580"}
            success = (event_cstat in success_event_codes) or (lote_cstat in success_event_codes)
            logger.info(
                "sefaz_manifest_response_parsed success=%s lote_cStat=%s lote_xMotivo=%s event_cStat=%s event_xMotivo=%s protocol=%s",
                str(success),
                lote_cstat,
                lote_xmotivo,
                event_cstat,
                event_xmotivo,
                event_protocol,
            )
            result_type = "processing_lot"
            if event_cstat in {"135", "136"}:
                result_type = "registered"
            elif event_cstat in {"573", "580"}:
                result_type = "already_registered"
            elif event_cstat:
                result_type = "rejected"
            elif lote_cstat == "128":
                result_type = "processing_lot"
            return {
                "success": success,
                "cStat": event_cstat or lote_cstat,
                "xMotivo": event_xmotivo or lote_xmotivo,
                "protocol": event_protocol,
                "dhRegEvento": event_registered_at,
                "tpEvento": event_type,
                "chNFe": event_access_key,
                "nSeqEvento": event_seq,
                "lote_cStat": lote_cstat,
                "lote_xMotivo": lote_xmotivo,
                "event_cStat": event_cstat,
                "event_xMotivo": event_xmotivo,
                "event_nProt": event_protocol,
                "event_dhRegEvento": event_registered_at,
                "event_tpEvento": event_type,
                "event_chNFe": event_access_key,
                "event_nSeqEvento": event_seq,
                "event_result_type": result_type,
                "raw_xml": xml_content.decode("utf-8", errors="ignore"),
            }
        except Exception as e:
            return {"success": False, "message": f"Erro parse manifestação: {e}"}

    def consultar_distribuicao_dfe(self, cnpj, ult_nsu="0", ambiente=1):
        """
        Consulta notas fiscais destinadas ao CNPJ (Distribuição DFe).
        ambiente: 1 = Produção, 2 = Homologação
        """
        # Formatar CNPJ (apenas números)
        cnpj = ''.join(filter(str.isdigit, str(cnpj)))
        ult_nsu = str(ult_nsu).zfill(15)
        
        # URL Dinâmica
        url = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        if int(ambiente) == 2:
            url = "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"

        xml_body = (
            '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
            f'<tpAmb>{ambiente}</tpAmb>'
            '<cUFAutor>26</cUFAutor>'
            f'<CNPJ>{cnpj}</CNPJ>'
            '<distNSU>'
            f'<ultNSU>{ult_nsu.zfill(15)}</ultNSU>'
            '</distNSU>'
            '</distDFeInt>'
        )

        envelope = self._build_soap_envelope(
            xml_body, 
            None, 
            None
        )

        return self._enviar_soap_distribuicao(envelope, url)

    def consultar_por_chave(self, chave, cnpj, ambiente=1):
        """
        Consulta XML da nota pela chave de acesso (consChNFe).
        """
        cnpj = ''.join(filter(str.isdigit, str(cnpj)))
        
        # URL Dinâmica
        url = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        if int(ambiente) == 2:
            url = "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        
        xml_body = (
            '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
            f'<tpAmb>{ambiente}</tpAmb>'
            '<cUFAutor>26</cUFAutor>'
            f'<CNPJ>{cnpj}</CNPJ>'
            '<consChNFe>'
            f'<chNFe>{chave}</chNFe>'
            '</consChNFe>'
            '</distDFeInt>'
        )

        envelope = self._build_soap_envelope(
            xml_body, 
            None, 
            None
        )
        
        return self._enviar_soap_distribuicao(envelope, url)

    def consultar_nsu(self, nsu, cnpj, ambiente=1):
        """
        Consulta um NSU específico (consNSU).
        """
        cnpj = ''.join(filter(str.isdigit, str(cnpj)))
        nsu = str(nsu).zfill(15)
        
        url = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        if int(ambiente) == 2:
            url = "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
        
        xml_body = (
            '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
            f'<tpAmb>{ambiente}</tpAmb>'
            '<cUFAutor>26</cUFAutor>'
            f'<CNPJ>{cnpj}</CNPJ>'
            '<consNSU>'
            f'<NSU>{nsu}</NSU>'
            '</consNSU>'
            '</distDFeInt>'
        )

        envelope = self._build_soap_envelope(
            xml_body, 
            None, 
            None
        )
        
        return self._enviar_soap_distribuicao(envelope, url)

    def _enviar_soap_distribuicao(self, envelope, url=None):
        if url is None:
            url = URL_DISTRIBUICAO # Fallback
            
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "SOAPAction": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse",
        }
        try:
            logger.info(f"SEFAZ SOAP Request Envelope: {envelope}")
            response = requests.post(
                url,
                data=envelope,
                headers=headers,
                cert=(self._cert_pem, self._key_pem),
                verify=False, # Ignorar validação SSL da SEFAZ (certificados gov não confiáveis por padrão)
                timeout=30
            )
            response.raise_for_status()
            return self._parse_distribuicao_response(response.content)
        except Exception as e:
            logger.error(f"Erro na requisição SOAP: {e}")
            return {"success": False, "message": str(e)}

    def parse_xml_content(self, xml_content):
        """
        Analisa o XML (resNFe ou procNFe) e retorna dados normalizados.
        """
        try:
            root = ET.fromstring(xml_content)
            # Remove namespaces para facilitar
            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]
            
            data = {}
            
            if root.tag == 'resNFe':
                data['type'] = 'resNFe'
                data['access_key'] = root.findtext('chNFe')
                data['cnpj_emitente'] = root.findtext('CNPJ')
                data['nome_emitente'] = root.findtext('xNome')
                data['ie_emitente'] = root.findtext('IE')
                data['dhemi'] = root.findtext('dhEmi')
                data['vnf'] = root.findtext('vNF')
                data['digval'] = root.findtext('digVal')
                data['date_received'] = root.findtext('dhRecbto')
                data['situation'] = root.findtext('cSitNFe') # 1=Autorizada, 2=Denegada, 3=Cancelada
                
            elif root.tag == 'nfeProc':
                data['type'] = 'nfeProc'
                nfe = root.find('NFe')
                inf_nfe = nfe.find('infNFe') if nfe else None
                if inf_nfe:
                    data['access_key'] = inf_nfe.get('Id', '').replace('NFe', '')
                    emit = inf_nfe.find('emit')
                    if emit:
                        data['cnpj_emitente'] = emit.findtext('CNPJ')
                        data['nome_emitente'] = emit.findtext('xNome')
                        data['ie_emitente'] = emit.findtext('IE')
                    ide = inf_nfe.find('ide')
                    if ide:
                        data['dhemi'] = ide.findtext('dhEmi')
                    total = inf_nfe.find('total/ICMSTot')
                    if total:
                        data['vnf'] = total.findtext('vNF')
                        
            elif root.tag == 'resEvento':
                data['type'] = 'resEvento'
                data['access_key'] = root.findtext('chNFe')
                data['tp_evento'] = root.findtext('tpEvento')
                data['desc_evento'] = root.findtext('xEvento')
                data['seq_evento'] = root.findtext('nSeqEvento')
                data['dh_evento'] = root.findtext('dhEvento')
                
            return data
        except Exception as e:
            logger.error(f"Erro parse XML content: {e}")
            return {}

    def _parse_distribuicao_response(self, xml_content):
        try:
            # Log raw response for debug
            logger.info(f"SEFAZ Raw Response: {xml_content.decode('utf-8', errors='ignore')}")
            
            # Remover namespaces para facilitar parsing
            xml_str = xml_content.decode('utf-8')
            # Gambiarra para remover namespaces (parser simples)
            # Ideal seria usar lxml ou tratar namespaces corretamente com ET
            
            root = ET.fromstring(xml_content)
            
            # Encontrar o retorno (retDistDFeInt) dentro do Body
            # Namespaces SOAP e NFe
            ns = {
                'soap12': 'http://www.w3.org/2003/05/soap-envelope',
                'nfe': 'http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe',
                'res': 'http://www.portalfiscal.inf.br/nfe'
            }
            
            # Navegar até o resultado
            # soap:Body -> nfe:nfeDistDFeInteresseResponse -> nfe:nfeDistDFeInteresseResult -> retDistDFeInt
            
            # Hack: buscar tag 'retDistDFeInt' direto no texto se o parser falhar ou for complexo
            # Mas vamos tentar via ET
            
            # Extrair o conteúdo de nfeDistDFeInteresseResult (que é um XML dentro do XML SOAP as vezes?)
            # Na verdade, o retorno é um XML embutido.
            
            # Vamos simplificar: buscar tags pelo nome local
            def find_all_by_tag(node, tag_name):
                return [e for e in node.iter() if e.tag.endswith(tag_name)]

            ret_nodes = find_all_by_tag(root, 'retDistDFeInt')
            if not ret_nodes:
                return {"success": False, "message": "Estrutura de resposta inválida (retDistDFeInt não encontrado)."}
            
            ret = ret_nodes[0]
            
            c_stat = ret.find('{http://www.portalfiscal.inf.br/nfe}cStat')
            if c_stat is None: c_stat = find_all_by_tag(ret, 'cStat')[0]
            
            x_motivo = ret.find('{http://www.portalfiscal.inf.br/nfe}xMotivo')
            if x_motivo is None: x_motivo = find_all_by_tag(ret, 'xMotivo')[0]
            
            status = c_stat.text
            message = x_motivo.text

            ult_nsu = ret.find('{http://www.portalfiscal.inf.br/nfe}ultNSU')
            if ult_nsu is None: 
                l = find_all_by_tag(ret, 'ultNSU')
                ult_nsu = l[0] if l else None
            
            max_nsu = ret.find('{http://www.portalfiscal.inf.br/nfe}maxNSU')
            if max_nsu is None: 
                l = find_all_by_tag(ret, 'maxNSU')
                max_nsu = l[0] if l else None

            ult_nsu_val = ult_nsu.text if ult_nsu is not None else None
            max_nsu_val = max_nsu.text if max_nsu is not None else None
            
            if status not in ['137', '138']: # 137: Nenhum documento, 138: Documentos encontrados
                return {
                    "success": False, 
                    "cStat": status, 
                    "message": message,
                    "ultNSU": ult_nsu_val,
                    "maxNSU": max_nsu_val
                }
            
            lote = ret.find('{http://www.portalfiscal.inf.br/nfe}loteDistDFeInt')
            if lote is None:
                lote_list = find_all_by_tag(ret, 'loteDistDFeInt')
                lote = lote_list[0] if lote_list else None
                
            docs = []
            if lote is not None:
                for doc_zip in find_all_by_tag(lote, 'docZip'):
                    nsu = doc_zip.attrib.get('NSU')
                    schema = doc_zip.attrib.get('schema')
                    content_b64 = doc_zip.text
                    
                    try:
                        content_xml = gzip.decompress(base64.b64decode(content_b64)).decode('utf-8')
                        docs.append({
                            'nsu': nsu,
                            'schema': schema,
                            'content': content_xml
                        })
                    except Exception as e:
                        logger.error(f"Erro ao descompactar doc {nsu}: {e}")
            
            return {
                "success": True,
                "cStat": status,
                "message": message,
                "ultNSU": ult_nsu_val,
                "maxNSU": max_nsu_val,
                "documents": docs
            }
            
        except Exception as e:
            logger.error(f"Erro parse resposta: {e}")
            return {"success": False, "message": f"Erro parse: {e}"}

