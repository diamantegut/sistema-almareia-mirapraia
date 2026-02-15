import os
import logging
import requests
import tempfile
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
import xml.etree.ElementTree as ET
import gzip
import base64
from datetime import datetime

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
            
        except Exception as e:
            logger.error(f"Erro ao carregar certificado PFX: {e}")
            raise

    def _cleanup(self):
        if self._temp_dir:
            self._temp_dir.cleanup()

    def _build_soap_envelope(self, body_content, method_name, namespace):
        # A SEFAZ utiliza SOAP 1.2
        # Envelope simplificado sem namespaces XSI/XSD não utilizados para evitar ruído
        return f'<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope"><soap12:Body><{method_name} xmlns="{namespace}"><nfeDadosMsg>{body_content}</nfeDadosMsg></{method_name}></soap12:Body></soap12:Envelope>'

    def consultar_distribuicao_dfe(self, cnpj, ult_nsu="0", ambiente=1):
        """
        Envia evento de Ciência da Operação (210210) para a SEFAZ.
        """
        xml_evento = self._gerar_xml_evento(chave_acesso, cnpj, "210210", "Ciencia da Operacao", ambiente)
        return self._enviar_evento(xml_evento, ambiente)

    def confirmar_operacao(self, chave_acesso, cnpj, ambiente=1):
        """
        Envia evento de Confirmação da Operação (210200) para a SEFAZ.
        """
        xml_evento = self._gerar_xml_evento(chave_acesso, cnpj, "210200", "Confirmacao da Operacao", ambiente)
        return self._enviar_evento(xml_evento, ambiente)

    def _gerar_xml_evento(self, chave, cnpj, tp_evento, desc_evento, ambiente):
        """Gera o XML assinado do evento."""
        # TODO: Implementar assinatura digital XML (SignedXml)
        # Como assinar XML em Python puro é complexo sem bibliotecas pesadas (signxml), 
        # e o usuário quer uma solução "grátis", vamos precisar de 'signxml' ou 'lxml' com openssl.
        # Por enquanto, vou deixar um placeholder e retornar erro se tentar usar sem a lib.
        
        # A manifestação exige assinatura digital no corpo do XML (tag <evento>).
        # Sem 'signxml' ou similar, é muito difícil fazer corretamente.
        # Vou assumir que posso usar 'signxml' se estiver instalado, ou falhar.
        
        try:
            import signxml
        except ImportError:
            raise Exception("Biblioteca 'signxml' necessária para assinar eventos. Instale com: pip install signxml lxml")

        # ... Implementação da assinatura ...
        return None 

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

        # Montar XML do pedido (distDFeInt) - Versão 1.01
        # cUFAutor: Deve ser a UF do interessado (26=PE), não 91 (AN) nem 35 (SP)
        # O CNPJ é de Pernambuco.
        xml_body = f'<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>{ambiente}</tpAmb><cUFAutor>26</cUFAutor><CNPJ>{cnpj}</CNPJ><distNSU><ultNSU>{ult_nsu}</ultNSU></distNSU></distDFeInt>'

        envelope = self._build_soap_envelope(
            xml_body, 
            "nfeDistDFeInteresse", 
            "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
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
        
        # Versão 1.01
        xml_body = f'<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>{ambiente}</tpAmb><cUFAutor>91</cUFAutor><CNPJ>{cnpj}</CNPJ><consChNFe><chNFe>{chave}</chNFe></consChNFe></distDFeInt>'

        envelope = self._build_soap_envelope(
            xml_body, 
            "nfeDistDFeInteresse", 
            "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
        )
        
        return self._enviar_soap_distribuicao(envelope, url)

    def _enviar_soap_distribuicao(self, envelope, url=None):
        if url is None:
            url = URL_DISTRIBUICAO # Fallback
            
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8; action=\"http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse\"",
        }
        try:
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
            
            if status not in ['137', '138']: # 137: Nenhum documento, 138: Documentos encontrados
                return {"success": False, "cStat": status, "message": message}
            
            ult_nsu = ret.find('{http://www.portalfiscal.inf.br/nfe}ultNSU')
            if ult_nsu is None: ult_nsu = find_all_by_tag(ret, 'ultNSU')[0]
            
            max_nsu = ret.find('{http://www.portalfiscal.inf.br/nfe}maxNSU')
            if max_nsu is None: max_nsu = find_all_by_tag(ret, 'maxNSU')[0]
            
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
                "ultNSU": ult_nsu.text,
                "maxNSU": max_nsu.text,
                "documents": docs
            }
            
        except Exception as e:
            logger.error(f"Erro parse resposta: {e}")
            return {"success": False, "message": f"Erro parse: {e}"}

